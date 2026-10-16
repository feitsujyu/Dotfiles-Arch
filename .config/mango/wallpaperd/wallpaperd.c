// wallpaperd —— 预加载式壁纸程序，替代 swaybg
//
// swaybg 不能在运行中更换图片，每次切换都要“启动新进程 → 解码 4K PNG → 缩放 → 显示”（实测 300～400 ms）。
// 这个程序在启动时就把每张壁纸按“每块屏幕的实际像素尺寸”准备好（wallpaper-cache.py 生成的原始像素文件），
// 直接作为显示缓冲区交给 mango；切换时只是“换一个缓冲区 + 提交”，不解码、不缩放、不复制。
//
// 控制：SIGUSR1 = 下一张，SIGUSR2 = 上一张（一般由 ~/.config/mango/scripts/wallpaper.sh 发送）
// PID 记在  $XDG_RUNTIME_DIR/mango-wallpaperd-$WAYLAND_DISPLAY.pid
// 当前壁纸记在 ~/.cache/mango-wallpaper（环境变量 WALLPAPER_STATE 可以改），重启后保持
// 壁纸目录：~/Pictures/background（png / jpg / jpeg，按文件名排序）

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/signalfd.h>
#include <sys/stat.h>
#include <unistd.h>
#include <wayland-client.h>

#include "fractional-scale-v1-client-protocol.h"
#include "viewporter-client-protocol.h"
#include "wlr-layer-shell-unstable-v1-client-protocol.h"

#define MAX_IMAGES 256

struct output {
	struct wl_list link;
	uint32_t global_name;
	struct wl_output *wl_output;
	struct wl_surface *surface;
	struct zwlr_layer_surface_v1 *layer;
	struct wp_viewport *viewport;
	struct wp_fractional_scale_v1 *fscale;
	uint32_t width, height;     // 逻辑尺寸（configure 给的）
	uint32_t scale120;          // 缩放倍数 × 120（fractional-scale 协议的单位），默认 120 = 100%
	uint32_t buf_w, buf_h;      // 当前已准备好的缓冲区像素尺寸
	struct wl_buffer *buffers[MAX_IMAGES];
	bool configured;
};

static struct wl_display *display;
static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct zwlr_layer_shell_v1 *layer_shell;
static struct wp_viewporter *viewporter;
static struct wp_fractional_scale_manager_v1 *fscale_mgr;
static struct wl_list outputs;

static char *images[MAX_IMAGES];
static int n_images;
static int current;
static char state_path[PATH_MAX];
static char cache_tool[PATH_MAX];
static bool running = true;

// ---------- 图片列表 / 状态 ----------

static int has_ext(const char *name) {
	const char *dot = strrchr(name, '.');
	return dot && (!strcasecmp(dot, ".png") || !strcasecmp(dot, ".jpg") || !strcasecmp(dot, ".jpeg"));
}

static int cmp_str(const void *a, const void *b) {
	return strcmp(*(char *const *)a, *(char *const *)b);
}

static void load_image_list(const char *dir) {
	DIR *d = opendir(dir);
	if (!d) {
		fprintf(stderr, "wallpaperd: cannot open %s: %s\n", dir, strerror(errno));
		exit(1);
	}
	struct dirent *e;
	while ((e = readdir(d)) && n_images < MAX_IMAGES) {
		if (e->d_name[0] == '.' || !has_ext(e->d_name))
			continue;
		char *p;
		if (asprintf(&p, "%s/%s", dir, e->d_name) < 0)
			exit(1);
		struct stat st;
		if (stat(p, &st) == 0 && S_ISREG(st.st_mode))
			images[n_images++] = p;
		else
			free(p);
	}
	closedir(d);
	qsort(images, n_images, sizeof(char *), cmp_str);
	if (n_images == 0) {
		fprintf(stderr, "wallpaperd: no images in %s\n", dir);
		exit(1);
	}
}

static void load_state(void) {
	current = 0;
	FILE *f = fopen(state_path, "r");
	if (!f)
		return;
	char line[PATH_MAX];
	if (fgets(line, sizeof line, f)) {
		line[strcspn(line, "\n")] = 0;
		for (int i = 0; i < n_images; i++)
			if (!strcmp(images[i], line))
				current = i;
	}
	fclose(f);
}

static void save_state(void) {
	char tmp[PATH_MAX + 8];
	snprintf(tmp, sizeof tmp, "%s.tmp", state_path);
	FILE *f = fopen(tmp, "w");
	if (!f)
		return;
	fprintf(f, "%s\n", images[current]);
	fclose(f);
	rename(tmp, state_path);
}

// ---------- 缓冲区 ----------

static void free_buffers(struct output *o) {
	for (int i = 0; i < n_images; i++) {
		if (o->buffers[i])
			wl_buffer_destroy(o->buffers[i]);
		o->buffers[i] = NULL;
	}
	o->buf_w = o->buf_h = 0;
}

// 调用 wallpaper-cache.py 生成 / 取得缓存文件，然后把文件直接作为 wl_shm 缓冲区（不读入、不复制）
static void prepare_buffers(struct output *o, uint32_t bw, uint32_t bh) {
	if (o->buf_w == bw && o->buf_h == bh)
		return;
	free_buffers(o);

	size_t len = strlen(cache_tool) + 64;
	for (int i = 0; i < n_images; i++)
		len += strlen(images[i]) * 4 + 4;
	char *cmd = malloc(len), *p = cmd;
	p += sprintf(p, "'%s' %u %u", cache_tool, bw, bh);
	for (int i = 0; i < n_images; i++) {  // 用单引号包起来传给 shell
		*p++ = ' ';
		*p++ = '\'';
		for (const char *s = images[i]; *s; s++) {
			if (*s == '\'') {
				memcpy(p, "'\\''", 4);
				p += 4;
			} else {
				*p++ = *s;
			}
		}
		*p++ = '\'';
	}
	*p = 0;

	FILE *pipe = popen(cmd, "r");
	free(cmd);
	if (!pipe)
		return;
	char line[PATH_MAX];
	size_t size = (size_t)bw * bh * 4;
	for (int i = 0; i < n_images && fgets(line, sizeof line, pipe); i++) {
		line[strcspn(line, "\n")] = 0;
		if (!line[0])
			continue;
		int fd = open(line, O_RDWR | O_CLOEXEC);
		struct stat st;
		if (fd < 0 || fstat(fd, &st) < 0 || (size_t)st.st_size != size) {
			if (fd >= 0)
				close(fd);
			continue;
		}
		struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
		o->buffers[i] = wl_shm_pool_create_buffer(pool, 0, bw, bh, bw * 4, WL_SHM_FORMAT_XRGB8888);
		wl_shm_pool_destroy(pool);
		close(fd);
	}
	pclose(pipe);
	o->buf_w = bw;
	o->buf_h = bh;
}

static void show(struct output *o) {
	if (!o->configured || !o->width || !o->height)
		return;
	uint32_t bw = (uint32_t)lround(o->width * o->scale120 / 120.0);
	uint32_t bh = (uint32_t)lround(o->height * o->scale120 / 120.0);
	prepare_buffers(o, bw, bh);
	struct wl_buffer *b = o->buffers[current];
	if (!b)
		return;
	wl_surface_attach(o->surface, b, 0, 0);
	if (o->viewport) {
		// 缓冲区是实际像素尺寸，viewport 告诉 mango 它对应多大的逻辑尺寸（小数缩放时不会模糊）
		wp_viewport_set_destination(o->viewport, o->width, o->height);
	}
	wl_surface_damage_buffer(o->surface, 0, 0, INT32_MAX, INT32_MAX);
	wl_surface_commit(o->surface);
}

// ---------- 协议回调 ----------

static void layer_configure(void *data, struct zwlr_layer_surface_v1 *l, uint32_t serial, uint32_t w, uint32_t h) {
	struct output *o = data;
	zwlr_layer_surface_v1_ack_configure(l, serial);
	o->width = w;
	o->height = h;
	o->configured = true;
	show(o);
}

static void destroy_output(struct output *o);

static void layer_closed(void *data, struct zwlr_layer_surface_v1 *l) {
	destroy_output(data);
}

static const struct zwlr_layer_surface_v1_listener layer_listener = {
	.configure = layer_configure,
	.closed = layer_closed,
};

static void preferred_scale(void *data, struct wp_fractional_scale_v1 *f, uint32_t scale) {
	struct output *o = data;
	if (o->scale120 != scale) {
		o->scale120 = scale;
		show(o);
	}
}

static const struct wp_fractional_scale_v1_listener fscale_listener = {
	.preferred_scale = preferred_scale,
};

static void setup_output(struct output *o) {
	o->surface = wl_compositor_create_surface(compositor);
	// 背景图不接收任何输入
	struct wl_region *empty = wl_compositor_create_region(compositor);
	wl_surface_set_input_region(o->surface, empty);
	wl_region_destroy(empty);

	if (viewporter)
		o->viewport = wp_viewporter_get_viewport(viewporter, o->surface);
	if (fscale_mgr) {
		o->fscale = wp_fractional_scale_manager_v1_get_fractional_scale(fscale_mgr, o->surface);
		wp_fractional_scale_v1_add_listener(o->fscale, &fscale_listener, o);
	}
	o->layer = zwlr_layer_shell_v1_get_layer_surface(layer_shell, o->surface, o->wl_output,
		ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND, "wallpaper");
	zwlr_layer_surface_v1_set_anchor(o->layer, 15);  // 上下左右都贴边 = 铺满整个屏幕
	zwlr_layer_surface_v1_set_exclusive_zone(o->layer, -1);
	zwlr_layer_surface_v1_set_size(o->layer, 0, 0);
	zwlr_layer_surface_v1_add_listener(o->layer, &layer_listener, o);
	wl_surface_commit(o->surface);
}

static void destroy_output(struct output *o) {
	free_buffers(o);
	if (o->fscale)
		wp_fractional_scale_v1_destroy(o->fscale);
	if (o->viewport)
		wp_viewport_destroy(o->viewport);
	if (o->layer)
		zwlr_layer_surface_v1_destroy(o->layer);
	if (o->surface)
		wl_surface_destroy(o->surface);
	if (o->wl_output) {
		if (wl_output_get_version(o->wl_output) >= 3)
			wl_output_release(o->wl_output);
		else
			wl_output_destroy(o->wl_output);
	}
	wl_list_remove(&o->link);
	free(o);
}

static void registry_global(void *data, struct wl_registry *r, uint32_t name, const char *iface, uint32_t ver) {
	if (!strcmp(iface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
	} else if (!strcmp(iface, wl_shm_interface.name)) {
		shm = wl_registry_bind(r, name, &wl_shm_interface, 1);
	} else if (!strcmp(iface, zwlr_layer_shell_v1_interface.name)) {
		layer_shell = wl_registry_bind(r, name, &zwlr_layer_shell_v1_interface, ver < 4 ? ver : 4);
	} else if (!strcmp(iface, wp_viewporter_interface.name)) {
		viewporter = wl_registry_bind(r, name, &wp_viewporter_interface, 1);
	} else if (!strcmp(iface, wp_fractional_scale_manager_v1_interface.name)) {
		fscale_mgr = wl_registry_bind(r, name, &wp_fractional_scale_manager_v1_interface, 1);
	} else if (!strcmp(iface, wl_output_interface.name)) {
		struct output *o = calloc(1, sizeof *o);
		o->global_name = name;
		o->scale120 = 120;
		o->wl_output = wl_registry_bind(r, name, &wl_output_interface, ver < 3 ? ver : 3);
		wl_list_insert(&outputs, &o->link);
		if (compositor && layer_shell)  // 启动后才接上的显示器
			setup_output(o);
	}
}

static void registry_global_remove(void *data, struct wl_registry *r, uint32_t name) {
	struct output *o, *tmp;
	wl_list_for_each_safe(o, tmp, &outputs, link) {
		if (o->global_name == name)
			destroy_output(o);
	}
}

static const struct wl_registry_listener registry_listener = {
	.global = registry_global,
	.global_remove = registry_global_remove,
};

// ---------- 主程序 ----------

static void step(int delta) {
	current = ((current + delta) % n_images + n_images) % n_images;
	struct output *o;
	wl_list_for_each(o, &outputs, link) show(o);
	wl_display_flush(display);
	save_state();
}

int main(void) {
	const char *home = getenv("HOME");
	const char *st = getenv("WALLPAPER_STATE");
	if (st)
		snprintf(state_path, sizeof state_path, "%s", st);
	else
		snprintf(state_path, sizeof state_path, "%s/.cache/mango-wallpaper", home);
	snprintf(cache_tool, sizeof cache_tool, "%s/.config/mango/wallpaperd/wallpaper-cache.py", home);

	char dir[PATH_MAX];
	snprintf(dir, sizeof dir, "%s/Pictures/background", home);
	load_image_list(dir);
	load_state();

	display = wl_display_connect(NULL);
	if (!display) {
		fprintf(stderr, "wallpaperd: cannot connect to wayland display\n");
		return 1;
	}
	wl_list_init(&outputs);
	struct wl_registry *registry = wl_display_get_registry(display);
	wl_registry_add_listener(registry, &registry_listener, NULL);
	wl_display_roundtrip(display);
	if (!compositor || !shm || !layer_shell) {
		fprintf(stderr, "wallpaperd: compositor lacks wl_compositor / wl_shm / layer-shell\n");
		return 1;
	}
	struct output *o;
	wl_list_for_each(o, &outputs, link) {
		if (!o->surface)
			setup_output(o);
	}

	// 用 signalfd 在主循环里接收信号
	sigset_t mask;
	sigemptyset(&mask);
	sigaddset(&mask, SIGUSR1);
	sigaddset(&mask, SIGUSR2);
	sigaddset(&mask, SIGTERM);
	sigaddset(&mask, SIGINT);
	sigprocmask(SIG_BLOCK, &mask, NULL);
	int sfd = signalfd(-1, &mask, SFD_CLOEXEC);

	char pidfile[PATH_MAX];
	const char *rt = getenv("XDG_RUNTIME_DIR");
	const char *wd = getenv("WAYLAND_DISPLAY");
	snprintf(pidfile, sizeof pidfile, "%s/mango-wallpaperd-%s.pid", rt ? rt : "/tmp", wd ? wd : "wayland-0");
	FILE *pf = fopen(pidfile, "w");
	if (pf) {
		fprintf(pf, "%d\n", getpid());
		fclose(pf);
	}

	struct pollfd fds[2] = {
		{ .fd = wl_display_get_fd(display), .events = POLLIN },
		{ .fd = sfd, .events = POLLIN },
	};
	while (running) {
		while (wl_display_prepare_read(display) != 0)
			wl_display_dispatch_pending(display);
		wl_display_flush(display);
		if (poll(fds, 2, -1) < 0) {
			wl_display_cancel_read(display);
			if (errno == EINTR)
				continue;
			break;
		}
		if (fds[0].revents & POLLIN) {
			if (wl_display_read_events(display) < 0)
				break;
		} else {
			wl_display_cancel_read(display);
		}
		if (fds[0].revents & (POLLERR | POLLHUP))
			break;  // mango 退出了
		if (wl_display_dispatch_pending(display) < 0)
			break;
		if (fds[1].revents & POLLIN) {
			struct signalfd_siginfo si;
			if (read(sfd, &si, sizeof si) == sizeof si) {
				if (si.ssi_signo == SIGUSR1)
					step(1);
				else if (si.ssi_signo == SIGUSR2)
					step(-1);
				else
					running = false;
			}
		}
	}

	pf = fopen(pidfile, "r");
	if (pf) {
		int pid = 0;
		if (fscanf(pf, "%d", &pid) == 1 && pid == getpid())
			unlink(pidfile);
		fclose(pf);
	}
	return 0;
}

/*
 * barprobe：找出 waybar 上鼠标所在的模块（胶囊）的左右边界
 *
 * 用法：barprobe <屏幕名> <宽> <缩放> <y> <x>
 *   屏幕名：eDP-1 等（mmsg get cursorpos 的 monitor）
 *   宽、缩放：这块屏幕的逻辑宽度和缩放比例（mmsg get monitor 的 width / scale）
 *   y, x  ：在这块屏幕内的坐标（逻辑坐标，和 mmsg 的单位相同），y 用栏的中间一行
 * 输出：  <左边> <右边>（逻辑坐标；右边 = 模块右边外侧的第一个像素）
 *
 * 做法：用 wlr-screencopy 只截取这块屏幕上 y 这一行（屏幕宽 × 1 像素），
 *       以这一行最右端的像素（时钟右边的空白 = 栏的底色）为基准，
 *       从 x 向左右找“和栏的底色不同”的范围（胶囊的底色、文字都算在模块里）。
 * 失败时（x 正好在模块之间的空隙上、截屏出错等）退出码不为 0，什么都不输出。
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "build/screencopy.h"

#define TOLERANCE 24  /* 和栏的底色的差（R+G+B）在这个以内就算栏的底色（栏是 0.97 不透明，壁纸透过来一点点） */

struct output { struct wl_output *wl; char name[64]; struct output *next; };
static struct output *outputs;
static struct wl_shm *shm;
static struct zwlr_screencopy_manager_v1 *manager;
static uint32_t fmt, W, H, S;
static unsigned char *data;
static int done;

static void out_geometry(void *d, struct wl_output *o, int32_t x, int32_t y, int32_t pw, int32_t ph,
                         int32_t sub, const char *make, const char *model, int32_t tr) {}
static void out_mode(void *d, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r) {}
static void out_done(void *d, struct wl_output *o) {}
static void out_scale(void *d, struct wl_output *o, int32_t s) {}
static void out_name(void *d, struct wl_output *o, const char *name) {
    snprintf(((struct output *)d)->name, sizeof ((struct output *)d)->name, "%s", name);
}
static void out_description(void *d, struct wl_output *o, const char *desc) {}
static const struct wl_output_listener output_listener = {
    out_geometry, out_mode, out_done, out_scale, out_name, out_description,
};

static void global(void *d, struct wl_registry *r, uint32_t n, const char *iface, uint32_t v) {
    if (!strcmp(iface, wl_shm_interface.name)) {
        shm = wl_registry_bind(r, n, &wl_shm_interface, 1);
    } else if (!strcmp(iface, wl_output_interface.name) && v >= 4) {  /* wl_output 的 name 事件从 version 4 开始才有 */
        struct output *o = calloc(1, sizeof *o);
        o->wl = wl_registry_bind(r, n, &wl_output_interface, 4);
        wl_output_add_listener(o->wl, &output_listener, o);
        o->next = outputs;
        outputs = o;
    } else if (!strcmp(iface, zwlr_screencopy_manager_v1_interface.name)) {
        manager = wl_registry_bind(r, n, &zwlr_screencopy_manager_v1_interface, 1);
    }
}
static void global_remove(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener registry_listener = { global, global_remove };

static void frame_buffer(void *d, struct zwlr_screencopy_frame_v1 *f, uint32_t format,
                         uint32_t w, uint32_t h, uint32_t stride) {
    fmt = format; W = w; H = h; S = stride;
    int fd = memfd_create("barprobe", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, (off_t)S * H) < 0) { done = -1; return; }
    data = mmap(NULL, (size_t)S * H, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, S * H);
    struct wl_buffer *buf = wl_shm_pool_create_buffer(pool, 0, W, H, S, format);
    wl_shm_pool_destroy(pool);
    close(fd);
    zwlr_screencopy_frame_v1_copy(f, buf);
}
static void frame_flags(void *d, struct zwlr_screencopy_frame_v1 *f, uint32_t flags) {}
static void frame_ready(void *d, struct zwlr_screencopy_frame_v1 *f, uint32_t a, uint32_t b, uint32_t c) { done = 1; }
static void frame_failed(void *d, struct zwlr_screencopy_frame_v1 *f) { done = -1; }
static const struct zwlr_screencopy_frame_v1_listener frame_listener = {
    frame_buffer, frame_flags, frame_ready, frame_failed,
};

/* 只比较 R+G+B 的差，所以 XRGB / XBGR 的顺序不用管 */
static int diff(const unsigned char *a, const unsigned char *b) {
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]);
}

int main(int argc, char **argv) {
    if (argc != 6) {
        fprintf(stderr, "usage: barprobe <output> <width> <scale> <y> <x>\n");
        return 2;
    }
    const char *name = argv[1];
    int32_t width = atoi(argv[2]);
    double scale = atof(argv[3]), y = atof(argv[4]), x = atof(argv[5]);
    if (width <= 0 || scale <= 0) return 2;

    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 1;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(display);  /* globals */
    wl_display_roundtrip(display);  /* wl_output 的 name */
    struct output *out = outputs;
    while (out && strcmp(out->name, name)) out = out->next;
    if (!shm || !manager || !out) return 1;

    /* 截取范围用逻辑坐标指定（超出屏幕的范围 mango 会直接失败，所以要给正确的宽度） */
    struct zwlr_screencopy_frame_v1 *frame =
        zwlr_screencopy_manager_v1_capture_output_region(manager, 0, out->wl, 0, (int32_t)y, width, 1);
    zwlr_screencopy_frame_v1_add_listener(frame, &frame_listener, NULL);
    while (!done && wl_display_dispatch(display) != -1)
        ;
    if (done < 0 || !data || W < 4) return 1;

    /* 截到的是物理像素（逻辑坐标 × 缩放） */
    scale = (double)W / width;
    int px = (int)(x * scale);
    if (px < 0 || px >= (int)W) return 1;

    const unsigned char *row = data;  /* H == 1（缩放时可能 > 1，只用第 1 行） */
    const unsigned char *bg = row + (W - 2) * 4;  /* 最右端：栏的底色 */
#define PX(i) (row + (size_t)(i) * 4)
    if (diff(PX(px), bg) <= TOLERANCE) return 1;  /* 点在模块之间的空隙上 */
    int left = px, right = px;
    while (left > 0 && diff(PX(left - 1), bg) > TOLERANCE) left--;
    while (right < (int)W - 1 && diff(PX(right + 1), bg) > TOLERANCE) right++;
    printf("%d %d\n", (int)(left / scale + 0.5), (int)((right + 1) / scale + 0.5));
    return 0;
}

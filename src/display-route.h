/* Panel and input priorities for the confirmation screen. */
#include <string.h>
#include <xf86drmMode.h>

enum panel_priority { PANEL_OTHER = 1, PANEL_DSI, PANEL_FLIP4_INNER };

static enum panel_priority panel_rank(unsigned connector_type, unsigned width, unsigned height) {
    if (connector_type != DRM_MODE_CONNECTOR_DSI)
        return PANEL_OTHER;
    return width == 1080 && height == 2640 ? PANEL_FLIP4_INNER : PANEL_DSI;
}

static int touch_rank(const char *name, int type_b, enum panel_priority panel) {
    if (!strcmp(name, "sec_touchpad") || !strcmp(name, "sec_touchscreen2"))
        return 0;
    if (!strcmp(name, "sec_touchscreen"))
        return panel == PANEL_FLIP4_INNER && type_b ? 3 : 0;
    return panel == PANEL_FLIP4_INNER ? 0 : (type_b ? 2 : 1);
}

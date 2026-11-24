/* Software-rendered confirmation using the selected DRM buffer's pitch. */
#include <ft2build.h>
#include FT_FREETYPE_H
#include <locale.h>
#include <string.h>
#include <wchar.h>

struct rect { int x, y, width, height; };

static struct rect confirm_button(int width, int height, int save) {
    return (struct rect){width * (save ? 55 : 15) / 100, height * 2 / 3,
                         width * 3 / 10, height / 6};
}

static void fill(void *pixels, const struct drm_mode_create_dumb *buffer,
                 struct rect rect, uint32_t color) {
    for (int y = rect.y; y < rect.y + rect.height; ++y) {
        uint32_t *row = (uint32_t *)((char *)pixels + (size_t)y * buffer->pitch);
        for (int x = rect.x; x < rect.x + rect.width; ++x)
            row[x] = color;
    }
}

static int render_text(void *pixels, const struct drm_mode_create_dumb *buffer, FT_Face font,
                       const char *text, int x, int baseline, int right, unsigned size) {
    mbstate_t state = {0};
    if (FT_Set_Pixel_Sizes(font, 0, size))
        return 1;
    size_t remaining = strlen(text);
    while (remaining) {
        wchar_t character;
        size_t bytes = mbrtowc(&character, text, remaining, &state);
        if (bytes == (size_t)-1 || bytes == (size_t)-2 || !bytes)
            return 1;
        FT_UInt glyph = FT_Get_Char_Index(font, character);
        if (!glyph || FT_Load_Glyph(font, glyph, FT_LOAD_RENDER))
            return 1;
        FT_GlyphSlot slot = font->glyph;
        int left = x + slot->bitmap_left;
        int top = baseline - slot->bitmap_top;
        FT_Bitmap *bitmap = &slot->bitmap;
        if (left < 0 || top < 0 || left + (int)bitmap->width > right ||
            top + bitmap->rows > buffer->height || bitmap->pitch < 0)
            return 1;
        for (unsigned row = 0; row < bitmap->rows; ++row) {
            uint32_t *dest = (uint32_t *)((char *)pixels + (top + row) * buffer->pitch);
            for (unsigned col = 0; col < bitmap->width; ++col) {
                unsigned alpha = bitmap->buffer[row * bitmap->pitch + col];
                uint32_t background = dest[left + col];
                uint32_t color = 0;
                for (unsigned shift = 0; shift < 24; shift += 8)
                    color |= (((background >> shift & 255) * (255 - alpha) + 255 * alpha) / 255) << shift;
                dest[left + col] = color;
            }
        }
        x += slot->advance.x >> 6;
        text += bytes;
        remaining -= bytes;
    }
    return 0;
}

static int draw_confirmation(void *pixels, const struct drm_mode_create_dumb *buffer, const char *text) {
    int width = buffer->width, height = buffer->height;
    int caption = width < 700 ? 24 : 36;
    int margin = width * 15 / 100;
    FT_Library library;
    FT_Face font;
    if (!setlocale(LC_CTYPE, "C.UTF-8") || FT_Init_FreeType(&library))
        return 1;
    if (FT_New_Face(library, "/usr/share/aios/NanumGothic-Regular.ttf", 0, &font)) {
        FT_Done_FreeType(library);
        return 1;
    }
    fill(pixels, buffer, (struct rect){0, 0, width, height}, 0x0012192d);
    fill(pixels, buffer, (struct rect){margin, height / 3, width - margin * 2, height / 6}, 0x0029324b);
    struct rect cancel = confirm_button(width, height, 0);
    struct rect save = confirm_button(width, height, 1);
    fill(pixels, buffer, cancel, 0x0038425a);
    fill(pixels, buffer, save, 0x00204caf);
    int error =
        render_text(pixels, buffer, font, "메모에 추가", margin, height / 4, width - margin, caption) ||
        render_text(pixels, buffer, font, text, margin + 24, height * 5 / 12 + caption / 2,
                    width - margin - 24, caption) ||
        render_text(pixels, buffer, font, "취소", cancel.x + 24, cancel.y + cancel.height / 2 + caption / 3,
                    cancel.x + cancel.width - 24, caption) ||
        render_text(pixels, buffer, font, "저장", save.x + 24, save.y + save.height / 2 + caption / 3,
                    save.x + save.width - 24, caption);
    FT_Done_Face(font);
    FT_Done_FreeType(library);
    return error;
}

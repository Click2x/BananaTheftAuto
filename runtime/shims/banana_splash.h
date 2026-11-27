#pragma once
// Banana Theft Auto: the splash window shown while the runtime prepares the title's shaders before the title goes on
// (LEONIDA_PRELOAD). A popup of its own on its own thread, since the title has drawn nothing yet: a dark card with the
// name, a banana-yellow progress bar and "Preparing shaders N / M".
#include <windows.h>

#include <atomic>
#include <cstdio>
#include <thread>

namespace rt::banana_splash {

struct State {
    std::atomic<unsigned> done{0}, total{0};
    std::atomic<HWND> window{nullptr};
    std::thread thread;
};

inline State& state() {
    static State s;
    return s;
}

inline LRESULT CALLBACK splash_proc(HWND w, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_TIMER:
        InvalidateRect(w, nullptr, FALSE);
        return 0;
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(w, &ps);
        RECT r;
        GetClientRect(w, &r);
        const int cw = r.right, ch = r.bottom;
        HDC mem = CreateCompatibleDC(dc);
        HBITMAP bmp = CreateCompatibleBitmap(dc, cw, ch);
        HGDIOBJ old = SelectObject(mem, bmp);
        HBRUSH bg = CreateSolidBrush(RGB(20, 18, 26)), track = CreateSolidBrush(RGB(48, 44, 58)),
               fill = CreateSolidBrush(RGB(255, 214, 31)), edge = CreateSolidBrush(RGB(255, 214, 31));
        FillRect(mem, &r, bg);
        RECT border{0, 0, cw, 4};
        FillRect(mem, &border, edge);
        SetBkMode(mem, TRANSPARENT);
        HFONT big = CreateFontW(34, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                                L"Segoe UI Emoji");
        HFONT note_font = CreateFontW(19, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                                  L"Segoe UI");
        HGDIOBJ old_font = SelectObject(mem, big);
        SetTextColor(mem, RGB(255, 214, 31));
        RECT title{0, 22, cw, 70};
        DrawTextW(mem, L"\U0001F34C Banana Theft Auto \U0001F34C", -1, &title, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        const unsigned done = state().done.load(), total = state().total.load();
        const double frac = total ? double(done) / double(total) : 0.0;
        const int bx = 40, bw = cw - 80, by = 96, bh = 18;
        RECT tr{bx, by, bx + bw, by + bh};
        FillRect(mem, &tr, track);
        RECT fr{bx, by, bx + int(bw * (frac > 1 ? 1 : frac)), by + bh};
        FillRect(mem, &fr, fill);
        SelectObject(mem, note_font);
        SetTextColor(mem, RGB(225, 222, 232));
        wchar_t line[160];
        std::swprintf(line, 160, L"Preparing shaders  %u / %u  (%d%%)", done, total, int(frac * 100));
        RECT lr{0, 124, cw, 150};
        DrawTextW(mem, line, -1, &lr, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        SetTextColor(mem, RGB(150, 146, 160));
        RECT nr{0, 150, cw, 176};
        DrawTextW(mem, L"The first launch builds them all; later launches reuse them.", -1, &nr,
                  DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        BitBlt(dc, 0, 0, cw, ch, mem, 0, 0, SRCCOPY);
        SelectObject(mem, old_font);
        DeleteObject(big);
        DeleteObject(note_font);
        DeleteObject(bg);
        DeleteObject(track);
        DeleteObject(fill);
        DeleteObject(edge);
        SelectObject(mem, old);
        DeleteObject(bmp);
        DeleteDC(mem);
        EndPaint(w, &ps);
        return 0;
    }
    case WM_USER + 1:  // finish()
        DestroyWindow(w);
        return 0;
    case WM_CLOSE:
        return 0;  // only finish() closes it
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(w, msg, wp, lp);
}

inline void start(unsigned total) {
    State& s = state();
    s.total = total;
    s.done = 0;
    s.thread = std::thread([] {
        WNDCLASSW wc{};
        wc.lpfnWndProc = splash_proc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.lpszClassName = L"BananaSplash";
        wc.hCursor = LoadCursor(nullptr, IDC_WAIT);
        RegisterClassW(&wc);
        const int w = 640, h = 200;
        const int x = (GetSystemMetrics(SM_CXSCREEN) - w) / 2, y = (GetSystemMetrics(SM_CYSCREEN) - h) / 2;
        HWND win = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, L"BananaSplash", L"Banana Theft Auto",
                                   WS_POPUP | WS_VISIBLE, x, y, w, h, nullptr, nullptr, wc.hInstance, nullptr);
        if (!win) return;
        // The process's first ShowWindow takes its launcher's show state (a minimized start would hide the splash):
        // the second one is the one that counts.
        ShowWindow(win, SW_SHOWNORMAL);
        ShowWindow(win, SW_SHOWNORMAL);
        state().window = win;
        SetTimer(win, 1, 250, nullptr);
        MSG msg;
        while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    });
}

inline void progress(unsigned done) { state().done = done; }

inline void finish() {
    State& s = state();
    // DestroyWindow must run on the window's own thread: ask it to, then wait for its loop to end. A very short
    // preload can finish before the window exists; give it a moment.
    for (int i = 0; i < 100 && !s.window.load() && s.thread.joinable(); ++i) Sleep(20);
    if (HWND w = s.window.exchange(nullptr)) PostMessageW(w, WM_USER + 1, 0, 0);
    if (s.thread.joinable()) s.thread.join();
}

}  // namespace rt::banana_splash

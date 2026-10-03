# SakuConvert 0.7.1 UI fixes

- Removed the large preview/analysis panel.
- Conversion button is always present and changes action text based on the detected file.
- Fixed post-file-selection state so the action button becomes available without resizing the window.
- Reduced layout height pressure so controls remain visible at the default window size.
- Kept conversion work in a background QThread.
- Worker thread is requested to stop before completion/error dialogs are shown.
- Document engine status is shown compactly in the status line.

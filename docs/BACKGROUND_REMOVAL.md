# Background Removal — v0.4

Background removal is an explicitly online optional feature.

BGNinja's current API documentation states:
- no API key/account required;
- 10 requests per day per IP;
- reset at midnight;
- max 99 MB and 30 MP per image;
- PNG, JPG, WEBP and HEIC input;
- PNG output;
- images are processed in memory and streamed back.

SakuConvert keeps a local daily-use counter so the UI can communicate the remaining allowance.

## Counter behavior

- Successful request: decrement local remaining count.
- HTTP 402 daily-limit response: lock the feature locally.
- At local date change: reset the UI counter to 10/10.
- The provider remains authoritative; the local counter is not a security boundary.

At 0/10 the button is disabled/visually faded and says:
`Remove Background — 0/10 • Tomorrow`

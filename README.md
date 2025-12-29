# CTP500 Printer App

## Diagnostics/Test Sequence

The Diagnostics panel provides a guided test sequence and raw command tools to verify
Bluetooth communication and printing responsiveness for the CTP500TL ("Mini Printer-DC20").

### Diagnostics and Discover controls
* Use **Show Diagnostics** to reveal the Diagnostics panel (hidden by default).
* **Printer MAC Address** is editable in the Connection section; click **Save** to persist it.
* **Printer Info** buttons send Status, Serial Number, and Product Info commands and log responses.
* **Discover** runs a curated, safe probe list and logs any bytes returned by the printer.
  Click **Stop Discover** to cancel.

### How to run diagnostics
1. Launch the app and connect to the printer with **Connect**.
   - The diagnostics sequence runs automatically after a successful connection.
2. To run it manually, open **Diagnostics** and click **Run Test Sequence**.
3. Use **Read Response** to attempt a short recv() and view any bytes returned by the printer.
4. Use **Send Raw Hex** to send raw commands (for example: `1B 40`).

### Diagnostics options
* **Use ESC * image mode**: print a tiny checkerboard via ESC `*` line-by-line.
* **Use GS v 0 raster mode**: print the same checkerboard via GS `v 0`.
* **Invert image bits**: invert the bitmap before sending.
* **Chunked writes**: send data in chunks to reduce Bluetooth buffer overruns.
  * **Chunk size**: defaults to 512 bytes.
  * **Inter-chunk delay (ms)**: defaults to 10 ms.

### What the outcomes mean
* **Feed works, text/image does not**: basic command path is alive; image mode may be wrong
  or needs inversion/chunking changes.
* **Text prints but image does not**: test toggling ESC `*` vs GS `v 0`, or try inversion.
* **Nothing prints but connect succeeds**: try enabling chunking, lowering chunk size,
  or increasing inter-chunk delay.
* **Response bytes appear**: the printer is acknowledging commands; log the bytes for analysis.
* **No response bytes**: still acceptable—many printers are silent; rely on feed/text/image output.

## Troubleshooting
* **Connection error: [Errno 16] Device or resource busy**: the app now serializes connect/disconnect,
  retries briefly with a small backoff, and cleans up any half-open RFCOMM sockets before reconnecting.
  If you still see it, wait a second after disconnecting and try again.

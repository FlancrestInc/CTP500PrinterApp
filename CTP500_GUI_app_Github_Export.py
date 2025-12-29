'''
Bluetooth LE CTP500 thermal printer client by Mel at ThirtyThreeDown Studio
See https://thirtythreedown.com/2025/11/02/pc-app-for-walmart-thermal-printer/ for process and details!
Shout out to Bitflip, Tsathoggualware, Reid and all the mad lasses and lads whose research made this possible!

'''

#System imports
import socket
import sys
from time import sleep
import struct
import binascii
import queue
import threading
import time
import select
import traceback

#Tkinter imports
import tkinter as tk
from tkinter import Frame, Label, Button, Text, Radiobutton, messagebox
from tkinter.messagebox import showinfo
from tkinter import filedialog as fd
from tkinter import scrolledtext

#PILLOW imports
import PIL.Image
import PIL.ImageTk
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageChops
import PIL.ImageOps

#COMMUNICATION LOGIC STARTS HERE
mac_address = "00:00:00:00:00:00" #Put in your printer's Bluetooth device address here - you can find it in the app

class PrinterConnect: #Starting a PrinterConnect class to keep track of connection status
    def __init__(self):
        self.socket = None #Starting a disconnect socket
        self.connected = False #Setting socket status to False/disconnected

    def connect(self, mac_address): #Setting up a connection function
        if self.connected: #Checking to see if the printer is already connected
            print("Already connected") #Warning user
            return True #Switching PrinterConnect socket status

        try: #Starting all the things to do to establish a connection
            self.socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) #Setting up the Bluetooth socket with RFCOMM protocol
            # Timeout protects against the OS or driver hanging indefinitely.
            # The CTP500TL can silently stall if a link is flaky, so we cap every blocking call.
            self.socket.settimeout(3)
            self.socket.connect((mac_address, 1)) #Connection instruction with address and port to use

            self.connected = True #Switching connection status for tracking
            print("Connection established")

            return True #Returning status

        except Exception as e: #Exception handling in case something goes wrong
            print(f'Connection error: {e}')
            if self.socket: #If the socket connection is present:
                self.socket.close() #Closing the connection
                self.socket = None #Clearing the socket references
            return False #Returning status

    def disconnect(self): #Function to disconnect the socket
        if not self.connected or not self.socket: #First a status check to see if already disconnected
            print("Not connected") #Communication to user
            return #Calling it a day

        try:
            print("Disconnecting printer")
            print("Releasing Bluetooth comm resources")
            self.socket.shutdown(socket.SHUT_RDWR) #Releasing comms resources

            print("Cutting connection")
            self.socket.close()

            print("Clearing socket references")
            self.socket = None #Clearing socket refs
            self.connected = False #Switching connection status tracking
            print("Disconnected")

        except Exception as e:
            print(f'Disconnection error: {e}') #Exception warning
            if self.socket: #In case of connection shutdown failure, we close anyway
                self.socket.close() #Closing socket
                self.socket = None #Clearing the socket
            self.connected = False #Setting socket status to false


    def get_printer_status(self):
        if not self.socket:
            raise Exception("Not connected")
        try:
            # Best-effort status request. Never block indefinitely while waiting on recv().
            self.socket.send(b"\x1e\x47\x03") #Hex code for status request
            ready, _, _ = select.select([self.socket], [], [], 0.5)
            if ready:
                return self.socket.recv(38) #Returning status request content
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Status query failed: {e}")
        return b""


printer = PrinterConnect() #Creating a printer connection instance here. Having it *outside* of a function lets us run and monitor connection across global scope
printerWidth = 384  # For CPT500
#PRINTER COMMUNICATION LOGIC AND SETUP ENDS HERE

#DEBUG/WORKER UTILITIES START HERE
def format_hex(data):
    return binascii.hexlify(data).decode("ascii")

def log_debug(debug_enabled, message):
    if debug_enabled:
        print(message)

def send_bytes_chunked(soc, data, debug_enabled, chunk_size=512, delay_s=0.01, label="Data"):
    """
    Send data in small chunks with tiny sleeps in between.
    This improves reliability on the CTP500TL by avoiding buffer overrun and
    gives the OS a chance to flush the Bluetooth stack.
    """
    total = len(data)
    if total == 0:
        return
    offset = 0
    last_time = time.monotonic()
    while offset < total:
        chunk = data[offset:offset + chunk_size]
        soc.send(chunk)
        now = time.monotonic()
        delta_ms = (now - last_time) * 1000
        log_debug(debug_enabled, f"{label} chunk {offset}-{offset + len(chunk)} ({len(chunk)} bytes), {delta_ms:.1f}ms since last chunk")
        log_debug(debug_enabled, f"{label} bytes: {format_hex(chunk)}")
        offset += len(chunk)
        last_time = now
        if delay_s:
            sleep(delay_s)
    log_incoming_bytes(soc, debug_enabled)

def log_incoming_bytes(soc, debug_enabled):
    if not debug_enabled:
        return
    try:
        ready, _, _ = select.select([soc], [], [], 0)
        if ready:
            data = soc.recv(1024)
            if data:
                print(f"Incoming bytes: {format_hex(data)}")
    except Exception as e:
        print(f"Incoming read failed: {e}")

class BluetoothWorker:
    def __init__(self, status_callback):
        self.status_callback = status_callback
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def enqueue(self, func, *args):
        self.queue.put((func, args))

    def shutdown(self):
        self.queue.put(None)

    def _run(self):
        while True:
            task = self.queue.get()
            if task is None:
                break
            func, args = task
            try:
                func(*args)
            except Exception as e:
                self.status_callback(f"Error: {e}")
            finally:
                self.queue.task_done()
#DEBUG/WORKER UTILITIES END HERE

#DIAGNOSTICS UTILITIES START HERE
diagnostics_log_widget = None

def format_hex_snippet(data, max_len=32):
    return format_hex(data[:max_len])

def log_diagnostics(message):
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    if diagnostics_log_widget:
        diagnostics_log_widget.after(0, lambda: _append_diag_log(line))
    else:
        print(line.strip())

def _append_diag_log(line):
    diagnostics_log_widget.configure(state="normal")
    diagnostics_log_widget.insert(tk.END, line)
    diagnostics_log_widget.see(tk.END)
    diagnostics_log_widget.configure(state="disabled")

def send_bytes(data, label="Data"):
    if not (printer.connected and printer.socket):
        log_diagnostics("Send failed: not connected")
        return False

    chunked = bool(diag_chunked_var.get())
    try:
        chunk_size = int(diag_chunk_size_var.get() or 512)
    except ValueError:
        chunk_size = 512
    try:
        delay_ms = float(diag_chunk_delay_var.get() or 10)
    except ValueError:
        delay_ms = 10
    delay_s = max(delay_ms, 0) / 1000.0
    total = len(data)
    if total == 0:
        log_diagnostics(f"{label}: no data to send")
        return True

    log_diagnostics(f"{label}: sending {total} bytes, chunked={chunked}, first32={format_hex_snippet(data)}")
    try:
        if not chunked:
            printer.socket.send(data)
            return True

        offset = 0
        while offset < total:
            chunk = data[offset:offset + chunk_size]
            printer.socket.send(chunk)
            log_diagnostics(f"{label}: chunk {offset}-{offset + len(chunk)} ({len(chunk)} bytes), delay={delay_ms:.1f}ms")
            offset += len(chunk)
            if delay_s:
                sleep(delay_s)
        return True
    except Exception:
        log_diagnostics("Send failed:\n" + traceback.format_exc())
        return False

def try_read(max_bytes=1024, timeout_s=0.3, label="Read"):
    if not (printer.connected and printer.socket):
        log_diagnostics("Read failed: not connected")
        return b""
    try:
        ready, _, _ = select.select([printer.socket], [], [], timeout_s)
        if not ready:
            log_diagnostics(f"{label}: no data within {timeout_s:.1f}s")
            return b""
        data = printer.socket.recv(max_bytes)
        if data:
            log_diagnostics(f"{label}: received {len(data)} bytes: {format_hex(data)}")
        else:
            log_diagnostics(f"{label}: no data received")
        return data
    except socket.timeout:
        log_diagnostics(f"{label}: recv timed out after {timeout_s:.1f}s")
    except Exception:
        log_diagnostics(f"{label} failed:\n" + traceback.format_exc())
    return b""

def build_checkerboard_image(size=16):
    img = PIL.Image.new("1", (size, size), 1)
    draw = PIL.ImageDraw.Draw(img)
    block = 4
    for y in range(0, size, block):
        for x in range(0, size, block):
            if ((x // block) + (y // block)) % 2 == 0:
                draw.rectangle((x, y, x + block - 1, y + block - 1), fill=0)
    return img

def pack_esc_star_rows(im):
    if im.mode != "1":
        im = im.convert("1")
    width = im.size[0]
    height = im.size[1]
    pixels = im.load()
    rows = []
    for row in range(0, height, 8):
        row_bytes = bytearray()
        for x in range(width):
            byte = 0
            for bit in range(8):
                y = row + bit
                if y < height:
                    bit_val = 1 if pixels[x, y] == 0 else 0
                else:
                    bit_val = 0
                byte |= (bit_val << (7 - bit))
            row_bytes.append(byte)
        rows.append(bytes(row_bytes))
    return rows

def build_gsv0_raster(im, invert=False):
    if im.width > printerWidth:
        height = int(im.height * (printerWidth / im.width))
        im = im.resize((printerWidth, height))
    if im.width < printerWidth:
        padded_image = PIL.Image.new("1", (printerWidth, im.height), 1)
        padded_image.paste(im)
        im = padded_image
    if im.mode != '1':
        im = im.convert('1')
    if im.size[0] % 8:
        im2 = PIL.Image.new('1', (im.size[0] + 8 - im.size[0] % 8, im.size[1]), 'white')
        im2.paste(im, (0, 0))
        im = im2
    if invert:
        im = PIL.ImageOps.invert(im.convert('L')).convert('1')

    buf = b''.join((bytearray(b'\x1d\x76\x30\x00'),
                    struct.pack('2B', int(im.size[0] / 8 % 256),
                                int(im.size[0] / 8 / 256)),
                    struct.pack('2B', int(im.size[1] % 256),
                                int(im.size[1] / 256)),
                    im.tobytes()))
    return buf

def run_diagnostics_sequence():
    try:
        log_diagnostics("Diagnostics: starting test sequence")
        if not (printer.connected and printer.socket):
            log_diagnostics("Step A: connecting...")
            if not printer.connect(mac_address):
                log_diagnostics("Step A: connection failed")
                return
            log_diagnostics("Step A: connected")
        else:
            log_diagnostics("Step A: already connected")

        log_diagnostics("Step B: initialize (ESC @)")
        send_bytes(b"\x1b\x40", label="Init")
        try_read(label="Init response")

        log_diagnostics("Step C: feed 3 lines (ESC d 03)")
        send_bytes(b"\x1b\x64\x03", label="Feed")
        try_read(label="Feed response")

        log_diagnostics("Step D: plain text print")
        payload = b"TEST PRINT 1\nTEST PRINT 2\n\n"
        payload += b"\x1b\x64\x03"
        send_bytes(payload, label="Text test")
        try_read(label="Text response")

        log_diagnostics("Step E: checkerboard image test")
        base_image = build_checkerboard_image(16)
        invert_bits = bool(diag_invert_var.get())

        if diag_use_esc_star_var.get():
            log_diagnostics("Step E1: ESC * image mode")
            esc_image = base_image
            if invert_bits:
                esc_image = PIL.ImageOps.invert(esc_image.convert("L")).convert("1")
            rows = pack_esc_star_rows(esc_image)
            for row_bytes in rows:
                header = b"\x1b\x2a\x00" + struct.pack("2B", len(row_bytes) % 256, len(row_bytes) // 256)
                send_bytes(header + row_bytes, label="ESC * row")
                send_bytes(b"\n", label="ESC * newline")
            try_read(label="ESC * response")

        if diag_use_gsv0_var.get():
            log_diagnostics("Step E2: GS v 0 raster mode")
            raster = build_gsv0_raster(base_image, invert=invert_bits)
            send_bytes(raster, label="GS v0 raster")
            try_read(label="GS v0 response")

        log_diagnostics("Diagnostics: sequence complete")
    except Exception:
        log_diagnostics("Diagnostics failed:\n" + traceback.format_exc())
#DIAGNOSTICS UTILITIES END HERE

#IMAGE DATA STORAGE STARTS HERE
current_image = None #Variable to store full resolution image
image_thumbnail = None #Variable to store image thumbnail
image_preview = None #Variable to store image preview for PhotoImage and canvas
#IMAGE DATA STORAGE ENDS HERE

#TEXT FILE MANAGEMENT STARTS HERE
def selectTextFile():
    textFilePath = fd.askopenfilename(
        title = "Open a text file",
        initialdir = "/"
    )

    showinfo(
        title="Selected file: ",
        message = textFilePath
    )

#SOMETHING WEIRD IS HAPPENING HERE, FAILURE TO CAPTURE INPUT FIELD
    if textFilePath:
        try:
            with open(textFilePath, 'r', encoding='utf-8') as textFile: #Using the file path we got from the user to read the file
                textFileContent=textFile.read()
                textInputField.delete('1.0', tk.END) #Clearing previously typed content
                textInputField.insert(tk.END, textFileContent) #Inserting the text file content

            #Insert some sort of status bar system here? Success messages and exception messages
            #Status Bar stuff
        except Exception as e:
            print("Woops, something went wrong.")
#TEXT FILE MANAGEMENT ENDS HERE

#TEXT AND IMAGE INPUT RENDERING AND PRINTING STARTS HERE
def create_text(text, font_name="Lucon.ttf", font_size=28):
    #Tweak to be able to change font w/ system fonts
    img = PIL.Image.new('RGB', (printerWidth, 5000), color=(255, 255, 255)) #Defines an RGB image, width is printer width, height is 5000px, color is white
    font = PIL.ImageFont.truetype(font_name, font_size) #Loads up font_name as the default font, at font_size default size

    d = PIL.ImageDraw.Draw(img) #Creates the d image object using the parameters above
    lines = [] #Creates an empty Python list to store lines of text
    for line in text.splitlines(): #Combing through text looking for line splits
        lines.append(get_wrapped_text(line, font, printerWidth)) #Creating a new lines list item at each line split
    lines = "\n".join(lines) #Recombining all the lines list items with a "\n" line jump instruction at each line break
    d.text((0, 0), lines, fill=(0, 0, 0), font=font) #Drawing our text onto our d object
    return trimImage(img) #Trimming down the unused height of the d object using the trimImage() function above

def get_wrapped_text(text: str, font: PIL.ImageFont.ImageFont, line_length: int): #Function to wrap the text to printer paper width
    lines = [''] #Empty list to store the lines
    for word in text.split(): #Iterating through the split words composing a sentence
        line = f'{lines[-1]} {word}'.strip() #Composing a "candidate line" out of words, one word at a time
        if font.getlength(line) <= line_length: #If the pixel length of the line is shorter than the printer width...
            lines[-1] = line #...We keep doing that!
        else:
            lines.append(word) #...Otherwise we create a new line in the list of lines, and continue from the next word on.
    return '\n'.join(lines) #Done processing the text, returning the lines dictionary as a text with line returns!

def print_from_entry():
    txt = textInputField.get("1.0", tk.END).strip() # Grab the text from the scrolled‑text widget
    if not txt:
        messagebox.showwarning("No text", "Please type or load some text.")
        return

    img = create_text(txt) #Turning the text to image

    if printer.connected and printer.socket: #Send the text to the printer over the printer.socket (if connected)
        debug_enabled = bool(debugModeVar.get())
        worker.enqueue(run_print_job, img, "Text print", debug_enabled)
    else:
        messagebox.showwarning("Not connected",
                               "Please connect to the printer first.")

def print_from_image():
    """Send the currently loaded image to the printer."""
    if not current_image:
        messagebox.showwarning("No image", "Please load an image first.")
        return

    if not (printer.connected and printer.socket):
        messagebox.showwarning("Not connected",
                               "Please connect to the printer first.")
        return

    debug_enabled = bool(debugModeVar.get())
    worker.enqueue(run_print_job, current_image, "Image print", debug_enabled)

def print_test_pattern():
    if not (printer.connected and printer.socket):
        messagebox.showwarning("Not connected",
                               "Please connect to the printer first.")
        return
    debug_enabled = bool(debugModeVar.get())
    img = create_test_pattern_image()
    worker.enqueue(run_print_job, img, "Test pattern", debug_enabled)


#IMAGE FILE SECTION STARTS HERE
def selectImageFile():
    global current_image, image_thumbnail, image_preview
    imageFilepath = fd.askopenfilename(
        title = "Open an image file",
        initialdir = "/",
        filetypes = (('PNG files', '*.png'), ('JPG files', '*.jpg'), ('jpeg files', '*.jpeg'), ('BMP files', '*.bmp'), ('SVG files', '*.svg'), ('all files', '*.*'))
        )

    showinfo(
        title="Selected file: ",
        message = imageFilepath
    )

#SOMETHING WEIRD IS HAPPENING HERE, FAILURE TO CAPTURE INPUT FIELD
    if imageFilepath:
        try:
            print("Opening image file")
            current_image = PIL.Image.open(imageFilepath, 'r') #Storing the image contents into imageFile variable
            print(current_image)
            image_thumbnail = current_image.copy() #Copying current_image into image_thumbnail
            print(image_thumbnail)
            image_thumbnail.thumbnail((300, 100)) #Resizing image_thumbail to canvas size (might not work)

            print("Generating preview")
            imageCanvas_width = imageCanvas.winfo_width() #Storing the width of the preview canvas
            imageCanvas_height = imageCanvas.winfo_height() #Storing the height of the preview canvas
            imageCanvas_x_center = imageCanvas_width//2 #Calculating x center of the preview canvas
            imageCanvas_y_center = imageCanvas_height//2 #Calculating y center of the preview canvas

            image_preview = PIL.ImageTk.PhotoImage(image_thumbnail) #Storing the thumbnail as a displayable object into image_preview
            imageCanvas.delete('all')  #Clearing any  previous image from the canvas display
            imageCanvas.create_image(imageCanvas_x_center, imageCanvas_y_center, anchor = "center", image=image_preview)  # Loading up the thumbnail into the center of the preview canvas

        except Exception as e:
            print("Woops, something went wrong.")
            print({e})
#IMAGE FILE SECTION ENDS HERE

def printImage(socket, im):
    if im.width > printerWidth:
        # Image is wider than printer resolution; scale it down proportionately
        height = int(im.height * (printerWidth / im.width))
        im = im.resize((printerWidth, height))

    if im.width < printerWidth:
        # Image is narrower than printer resolution; pad it out with white pixels
        padded_image = PIL.Image.new("1", (printerWidth, im.height), 1)
        padded_image.paste(im)
        im = padded_image

    #Add a function for text rotation
    # im = im.rotate(180)  # Print it so it looks right when spewing out of the mouth

    # If image is not 1-bit, convert it
    if im.mode != '1':
        im = im.convert('1')

    # If image width is not a multiple of 8 pixels, fix that
    if im.size[0] % 8:
        im2 = PIL.Image.new('1', (im.size[0] + 8 - im.size[0] % 8, im.size[1]), 'white')
        im2.paste(im, (0, 0))
        im = im2

    # Invert image, via greyscale for compatibility
    im = PIL.ImageOps.invert(im.convert('L'))
    # ... and now convert back to single bit
    im = im.convert('1')

    buf = b''.join((bytearray(b'\x1d\x76\x30\x00'),
                    struct.pack('2B', int(im.size[0] / 8 % 256),
                                int(im.size[0] / 8 / 256)),
                    struct.pack('2B', int(im.size[1] % 256),
                                int(im.size[1] / 256)),
                    im.tobytes()))

    return buf

def trimImage(im):
    bg = PIL.Image.new(im.mode, im.size, (255, 255, 255))
    diff = PIL.ImageChops.difference(im, bg)
    diff = PIL.ImageChops.add(diff, diff, 2.0)
    bbox = diff.getbbox()
    if bbox:
        return im.crop((bbox[0], bbox[1], bbox[2], bbox[3] + 10))  # Don't cut off the end of the image

def initializePrinter(soc, debug=False):
    send_bytes_chunked(soc, b"\x1b\x40", debug, label="Init")

def sendStartPrintSequence(soc, debug=False):
    #Check against hex dump
    send_bytes_chunked(soc, b"\x1d\x49\xf0\x19", debug, label="Start print")

def sendEndPrintSequence(soc, debug=False):
    #Check against hex dump. Missings \x9a?
    send_bytes_chunked(soc, b"\x0a\x0a\x0a\x9a", debug, label="End print")

#TEXT AND IMAGE INPUT RENDERING AND PRINTING ENDS HERE

def create_test_pattern_image():
    # Simple, reliable pattern using the same raster pipeline as normal prints.
    img = PIL.Image.new("1", (printerWidth, 200), 1)
    draw = PIL.ImageDraw.Draw(img)
    draw.rectangle((0, 0, printerWidth - 1, 199), outline=0, fill=1)
    for y in range(0, 200, 16):
        for x in range(0, printerWidth, 16):
            if (x // 16 + y // 16) % 2 == 0:
                draw.rectangle((x, y, x + 15, y + 15), fill=0)
    draw.text((8, 8), "HELLO", fill=0)
    return img

def run_print_job(image, job_name, debug_enabled):
    if not (printer.connected and printer.socket):
        update_status("Not connected")
        return
    try:
        update_status(f"{job_name}: initializing")
        initializePrinter(printer.socket, debug_enabled)
        sleep(0.2)

        update_status(f"{job_name}: starting")
        sendStartPrintSequence(printer.socket, debug_enabled)
        sleep(0.2)

        update_status(f"{job_name}: sending image")
        buf = printImage(printer.socket, image)
        send_bytes_chunked(printer.socket, buf, debug_enabled, chunk_size=512, delay_s=0.01, label="Print data")

        update_status(f"{job_name}: finishing")
        sleep(0.2)
        sendEndPrintSequence(printer.socket, debug_enabled)
        update_status(f"{job_name}: done")
    except Exception as e:
        update_status(f"{job_name} failed: {e}")

def run_connect():
    update_status("Connecting...")
    if printer.connect(mac_address):
        update_status("Connected")
        print("Getting printer status (best effort)")
        status = printer.get_printer_status()
        print(f'Printer status: {status}')
        run_diagnostics_sequence()
    else:
        update_status("Connection failed")

def run_disconnect():
    update_status("Disconnecting...")
    printer.disconnect()
    update_status("Disconnected")

def run_send_raw_hex():
    raw = diag_raw_hex_var.get().strip()
    if not raw:
        log_diagnostics("Raw hex: no data provided")
        return
    try:
        cleaned = raw.replace(" ", "").replace("\n", "").replace("\t", "")
        data = binascii.unhexlify(cleaned)
    except Exception:
        log_diagnostics("Raw hex parse failed:\n" + traceback.format_exc())
        return
    log_diagnostics(f"Raw hex send: {raw}")
    send_bytes(data, label="Raw hex")

def run_read_response():
    try_read(label="Manual read")

#GUI SETUP STARTS HERE

root = tk.Tk()
frame = Frame(root)
frame.pack()

#Setting up window properties
root.title("CTP500 Printer Control")
root.configure() #Sets background color of the window. We will tweak this later to be able to select from printer colors and patterns
root.minsize(520, 600) #Sets min size of the window
root.geometry("520x600") #Changes original rendering position of the window

#Status + debug controls
statusVar = tk.StringVar(value="Disconnected")
debugModeVar = tk.IntVar(value=0)

def update_status(message):
    root.after(0, lambda: statusVar.set(message))

worker = BluetoothWorker(update_status)

#BLUETOOTH TOOLS SECTION STARTS HERE
bluetoothFrame = Frame(root,
                       borderwidth=1,
                       padx=5,
                       pady=5)

bluetoothLabel = Label(bluetoothFrame, text = "Bluetooth tools")
bluetoothLabel.pack(fill="x")

#Setting up connection button
connectButton = tk.Button(
    bluetoothFrame,
    text = "Connect",
    command=lambda: worker.enqueue(run_connect),
    padx = 15,
    pady = 15
).pack(
    side="left",
    expand=1
)

#Setting up disconnection button
disconnectButton = tk.Button(
    bluetoothFrame,
    text = "Disconnect",
    command=lambda: worker.enqueue(run_disconnect),
    padx = 15,
    pady = 15
).pack(
    side="left",
    expand=1
)

bluetoothFrame.pack() #Rendering bluetoothFrame

debugFrame = Frame(root, padx=5, pady=5)
debugCheckbox = tk.Checkbutton(
    debugFrame,
    text="Debug mode (log bytes/chunks)",
    variable=debugModeVar
)
debugCheckbox.pack(side="left")
debugFrame.pack(fill="x")

statusFrame = Frame(root, padx=5, pady=5)
statusLabelTitle = Label(statusFrame, text="Status:")
statusLabelTitle.pack(side="left")
statusLabelValue = Label(statusFrame, textvariable=statusVar, anchor="w")
statusLabelValue.pack(side="left", fill="x", expand=True)
statusFrame.pack(fill="x")
#BLUETOOTH TOOLS SECTION ENDS HERE

#TEXT TOOLS SECTION STARTS HERE
textFrame = Frame(root)
radioButtonsFrame = Frame(textFrame)

#Creating our list of justification options
justification_options = ["left",
                 "center",
                 "right"]
radioJustification_status = tk.IntVar() #Creating a watch state for the radio buttons for justification

textLabel = Label(textFrame, text="Text tools")
textLabel.pack(fill="x") #Text label for the text input section

for index in range(len(justification_options)): #Iterating through the list of justification options
    Radiobutton(radioButtonsFrame,
                text=justification_options[index],
                variable=radioJustification_status,
                value=index, padx=5).pack(side="left", expand=True) #Creating a button for each justification option

radioButtonsFrame.pack(fill="x", pady=(0, 5)) #Rendering the frame for the Justification radio buttons
#radioButtonsFrame.pack(fill="x", expand=1) #Rendering the frame for the Justification radio buttons

textInputField = scrolledtext.ScrolledText(textFrame, height=5, width=40) #Creating a text input widget to input text
textInputField.pack(fill="both") #Rendering the text input widget
textButton = Button(textFrame,
                    text="Select a text file",
                    padx=10, pady=15,
                    command=selectTextFile)
textButton.pack(expand=1, fill="x")
textFrame.pack(fill="both") #Rendering the text input area frame

#Creating a frame for the Print Text button
# printTextFrame = Frame(textFrame)
printTextButton = Button(textFrame,
                         text="Print your text!",
                         padx=10, pady=15,
                         command=print_from_entry)
printTextButton.pack(fill="x", pady=(5, 0))
# printTextFrame.pack(side="bottom", expand=1, fill="x")
#TEXT TOOLS SECTION ENDS HERE

#IMAGE TOOLS SECTION STARTS HERE
#Creating a frame for the image selection area
imageFrame = Frame(root)
imageLabel = Label(imageFrame, text="Image tools").pack(fill="x", pady=(0,5))

#Creating a canvas to display the image selection
imageCanvas = tk.Canvas(imageFrame,
                        width=300,
                        height=100,
                        bg = "white")
imageCanvas.pack(pady=(0,5)) #Rendering the image selection canvas

imageDisplay = Frame(imageFrame).pack(fill="both")  #Rendering the selected image to the image selection area

imageButton = Button(imageFrame,
                     text="Select an image file",
                     padx=10, pady=15,
                     command=selectImageFile)
imageButton.pack(fill="x")
#Displaying selected picture

#Creating a frame for the Print Image button
#printImageFrame = Frame(imageFrame)
printImageButton = Button(imageFrame,
                          text="Print your image!",
                          padx=10, pady=15,
                          command=print_from_image)
printImageButton.pack(fill="x", pady=(5, 0))

printTestButton = Button(imageFrame,
                         text="Print Test Pattern",
                         padx=10, pady=15,
                         command=print_test_pattern)
printTestButton.pack(fill="x", pady=(5, 0))
imageFrame.pack(fill="both", expand=True, padx=10, pady=5)
#IMAGE TOOLS SECTION ENDS HERE

#DIAGNOSTICS SECTION STARTS HERE
diagnosticsFrame = Frame(root, padx=5, pady=5, borderwidth=1)
diagnosticsLabel = Label(diagnosticsFrame, text="Diagnostics")
diagnosticsLabel.pack(fill="x")

diag_use_esc_star_var = tk.IntVar(value=1)
diag_use_gsv0_var = tk.IntVar(value=0)
diag_invert_var = tk.IntVar(value=0)
diag_chunked_var = tk.IntVar(value=1)
diag_chunk_size_var = tk.StringVar(value="512")
diag_chunk_delay_var = tk.StringVar(value="10")
diag_raw_hex_var = tk.StringVar(value="")

diagButtonFrame = Frame(diagnosticsFrame)
diagRunButton = Button(diagButtonFrame,
                       text="Run Test Sequence",
                       padx=10, pady=8,
                       command=lambda: worker.enqueue(run_diagnostics_sequence))
diagRunButton.pack(side="left", expand=True, fill="x")
diagReadButton = Button(diagButtonFrame,
                        text="Read Response",
                        padx=10, pady=8,
                        command=lambda: worker.enqueue(run_read_response))
diagReadButton.pack(side="left", expand=True, fill="x", padx=(5, 0))
diagButtonFrame.pack(fill="x", pady=(5, 5))

diagOptionsFrame = Frame(diagnosticsFrame)
tk.Checkbutton(diagOptionsFrame, text="Use ESC * image mode", variable=diag_use_esc_star_var).grid(row=0, column=0, sticky="w")
tk.Checkbutton(diagOptionsFrame, text="Use GS v 0 raster mode", variable=diag_use_gsv0_var).grid(row=1, column=0, sticky="w")
tk.Checkbutton(diagOptionsFrame, text="Invert image bits", variable=diag_invert_var).grid(row=2, column=0, sticky="w")
tk.Checkbutton(diagOptionsFrame, text="Chunked writes", variable=diag_chunked_var).grid(row=3, column=0, sticky="w")
Label(diagOptionsFrame, text="Chunk size").grid(row=3, column=1, sticky="e", padx=(10, 2))
tk.Entry(diagOptionsFrame, textvariable=diag_chunk_size_var, width=8).grid(row=3, column=2, sticky="w")
Label(diagOptionsFrame, text="Inter-chunk delay (ms)").grid(row=4, column=1, sticky="e", padx=(10, 2))
tk.Entry(diagOptionsFrame, textvariable=diag_chunk_delay_var, width=8).grid(row=4, column=2, sticky="w")
diagOptionsFrame.pack(fill="x", pady=(0, 5))

diagRawFrame = Frame(diagnosticsFrame)
Label(diagRawFrame, text="Send Raw Hex").pack(side="left")
tk.Entry(diagRawFrame, textvariable=diag_raw_hex_var, width=25).pack(side="left", padx=(5, 5))
Button(diagRawFrame, text="Send", command=lambda: worker.enqueue(run_send_raw_hex)).pack(side="left")
diagRawFrame.pack(fill="x", pady=(0, 5))

diagnostics_log_widget = scrolledtext.ScrolledText(diagnosticsFrame, height=8, width=60, state="disabled")
diagnostics_log_widget.pack(fill="both", expand=True)
diagnosticsFrame.pack(fill="both", expand=True, padx=10, pady=5)
#DIAGNOSTICS SECTION ENDS HERE

def on_closing(): #Cleanup operations when closing the window
    printer.disconnect() #Disconnecting the printer
    worker.shutdown()
    root.destroy() #Flushing the UI

root.protocol("WM_DELETE_WINDOW", on_closing) #Final window cleanup on app closing

root.mainloop() #If your mainloop() runs before your options, then nothing will show up. Keep that in mind!

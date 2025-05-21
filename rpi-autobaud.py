#!/usr/bin/env python3
# Detect the baud rate on a serial port of the Raspberry Pi by using the `pinctrl poll` command
# to analyze the times between level changes.

import subprocess
import time
import re
import sys
import os
import argparse

# Default configuration
BAUD_RATES = [4800, 9600, 19200, 38400, 57600, 115200, 230400]
CONFIDENCE_RATIO = 2.0  # Best score must be this much better than second-best
MIN_SAMPLES = 40        # Minimum required number of intervals
DESIRED_SAMPLES = 200   # Desired number of intervals for optimal results

def main():
    args = parse_args()
    
    timeout = args.timeout
    global verbose
    verbose = args.verbose 
    
    # Get GPIO pin
    gpio_pin = args.gpio if args.gpio else find_rx_gpio_pin(args.device)
    
    log(f"Detecting baud rate on GPIO{gpio_pin} (device: {args.device})")
    log(f"Sampling for {timeout} seconds...")

    intervals = collect_intervals(gpio_pin, timeout)
    
    # Analyze intervals and determine baud rate
    baud, best_error, confidence = select_baud_rate(intervals)
    
    # Make decision based on returned values
    if confidence >= CONFIDENCE_RATIO:
        # Only output the baud rate to stdout
        print(baud)
        sys.exit(0)
    else:
        eprint(f"Baud rate detection was inconclusive: best guess {baud} baud, error: {best_error:.4f}, confidence: {confidence:.2f}")
        sys.exit(2)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Auto-detect baud rate on a Raspberry Pi serial port')
    parser.add_argument('-d', '--device', type=str, default="ttyAMA0",
                      help='Serial device (e.g., ttyAMA0, ttyAMA3, default: ttyAMA0)')
    parser.add_argument('-g', '--gpio', type=str,
                      help='GPIO pin number (overrides device)')
    parser.add_argument('-t', '--timeout', type=float, default=1.0,
                      help='Sample duration in seconds (default: 1.0)')
    parser.add_argument('-v', '--verbose', action='store_true',
                      help='Enable verbose output')
    return parser.parse_args()

def find_rx_gpio_pin(device):
    """Find the GPIO pin number for the RX pin of the specified device"""
    try:
        # Check if the device name is properly formatted (ttyAMA followed by digits)
        # Remove optional /dev/ prefix if present
        if device.startswith("/dev/"):
            device = device[5:]
            
        # Verify device name format
        device_match = re.match(r'^ttyAMA(\d+)$', device)
        if not device_match:
            fatal(f"Error: Invalid device name '{device}'. Must be in format 'ttyAMA<n>' or '/dev/ttyAMA<n>'")
            
        # Extract the device number
        device_num = device_match.group(1)
        
        # Run pinctrl command to get pin information
        result = subprocess.run(["pinctrl"], stdout=subprocess.PIPE, text=True)
        if result.returncode != 0:
            fatal("Failed to run pinctrl")
            
        # Look for lines ending with "= RXD" followed by device number
        pattern = r'(\d+):.*=\s+RXD' + device_num + r'$'
        for line in result.stdout.splitlines():
            match = re.search(pattern, line)
            if match:
                gpio_pin = match.group(1)
                log(f"Found RX pin for {device}: GPIO{gpio_pin}")
                return gpio_pin
                
        log(f"Could not find RX pin for {device}")
        log("Available pins:")
        log(result.stdout)
        fatal(f"No RX pin found for device {device}")
    except Exception as e:
        fatal(f"Error finding RX GPIO pin: {e}")

def collect_intervals(gpio_pin, timeout):
    """Collect signal transition intervals from GPIO pin"""
    intervals = []
    start_time = time.time()

    # Launch pinctrl poll as subprocess
    proc = subprocess.Popen(["pinctrl", "poll", gpio_pin], stdout=subprocess.PIPE, text=True)
    
    # Ensure stdout is available
    if proc.stdout is None:
        fatal("Failed to open subprocess stdout")
    
    # Set non-blocking mode
    os.set_blocking(proc.stdout.fileno(), False)

    try:
        # Continue until we either get the desired number of samples or time runs out
        while time.time() - start_time < timeout and len(intervals) < DESIRED_SAMPLES:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            match = re.match(r"\+(\d+)us", line)
            if match:
                us = int(match.group(1))
                intervals.append(us)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait()

    if not intervals:
        fatal("No output detected")

    intervals = intervals[1:]  # Skip first interval as it may be unreliable

    # Only error out if we don't meet the minimum required sample count
    if len(intervals) < MIN_SAMPLES:
        fatal(f"Only {len(intervals)} samples collected, which is below the required minimum of {MIN_SAMPLES}.")

    log(f"Collected {len(intervals)} samples")
    return intervals

def select_baud_rate(intervals):
    """Determine baud rate by clustering the intervals into buckets and
    finding the first local maximum in a convolved histogram (±3 around each bucket).
    
    Buckets represent interval values in µs from 1 up to n_bucket-1.
    The first local maximum is assumed to be the one‑bit period.
    """
    n_bucket = 250
    window = 3  # ±3 µs

    # Create histogram for buckets 1 to n_bucket-1
    buckets = [0] * n_bucket  # Index 0 unused.
    for s in intervals:
        if 1 <= s < n_bucket:
            buckets[s] += 1

    # Convolve the histogram with a window of ±3
    conv = [0] * n_bucket
    for i in range(1, n_bucket):
        start = max(1, i - window)
        end = min(n_bucket - 1, i + window)
        conv[i] = sum(buckets[j] for j in range(start, end + 1))

    # Use first local maximum as estimated bit period
    estimated_bit = n_bucket - 1
    for i in range(2, n_bucket):
        if conv[i] < conv[i - 1]:
            estimated_bit = i - 1
            break

    # Compare the estimated bit period with each candidate baud's expected bit period
    # using a relative error metric.
    results = []
    for baud in BAUD_RATES:
        bit_period = 1_000_000 / baud  # Expected bit period in µs for this baud rate
        rerror = abs(bit_period - estimated_bit) / bit_period
        results.append((baud, bit_period, rerror))

    results.sort(key=lambda x: x[2])
    best_baud, best_bit_period, best_error = results[0]

    # Confidence: ratio of the second best error to the best one.
    if len(results) > 1 and best_error != 0:
        confidence = results[1][2] / best_error
    else:
        confidence = float('inf')

    log(f"Estimated one-bit period: {estimated_bit} µs, "
        f"Selected baud: {best_baud} (expected period: {best_bit_period:.2f} µs), "
        f"Relative error: {best_error:.4f}, Confidence: {confidence:.2f}")
    return best_baud, best_error, confidence

def fatal(msg):
    """Log a fatal error message and exit with the status 1"""
    eprint(msg)
    sys.exit(1)

def log(msg):
    """Print message to stderr if verbose mode is enabled"""
    if verbose:
        eprint(msg)

def eprint(msg):
    """Print message to stderr"""
    print(msg, file=sys.stderr)

if __name__ == "__main__":
    main()

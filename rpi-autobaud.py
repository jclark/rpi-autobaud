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
BAUD_RATES = [4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
CONFIDENCE_RATIO = 2.0  # Best score must be this much better than second-best
MAX_ABS_ERROR = 0.05    # Max normalized average error for a confident match
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
    if confidence >= CONFIDENCE_RATIO and best_error < MAX_ABS_ERROR:
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
    """Analyze intervals to determine the most likely baud rate"""
    # Score each baud rate using normalized squared error
    results = []
    for baud in BAUD_RATES:
        bit_us = 1_000_000 / baud
        error_sq_sum = 0
        count = 0
        for interval in intervals:
            n = round(interval / bit_us)
            if n == 0:
                continue
            quantized = n * bit_us
            relative_error = (interval - quantized) / bit_us
            error_sq_sum += relative_error * relative_error
            count += 1
        if count > 0:
            avg_error = error_sq_sum / count
            results.append((avg_error, baud))

    if not results:
        fatal("No valid baud candidates found - detected intervals are too short for standard baud rates.\n"
              "This may indicate a high-frequency signal or noise on the pin.")

    results.sort()
    best_error, best_baud = results[0]

    # Calculate confidence ratio
    if len(results) >= 2:
        second_error, second_baud = results[1]
        confidence = (second_error / best_error) if best_error > 0 else float('inf')
    else:
        # Only one candidate, set confidence to infinity
        confidence = float('inf')

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

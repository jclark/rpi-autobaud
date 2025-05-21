This is a utility to detect the baud rate of a UART on a Raspberry Py by analyzing the timing of signal level changes on the GPIO pin.

This uses the [pinctrl](https://github.com/raspberrypi/utils/blob/master/pinctrl/README.md) command with a `poll` argument to get the timings.

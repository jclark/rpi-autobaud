This is a utility to detect the baud rate of a device attached to a UART on a Raspberry Pi by analyzing the timing of signal level changes on the GPIO pin.

This uses the [pinctrl](https://github.com/raspberrypi/utils/blob/master/pinctrl/README.md) command with a `poll` argument to get the timings.

My particular application for this is determing the baud rate of a GPS receiver connected to a CM4/5 for my [satpulse](https://satpulse.net) project. So I am only handling standard baud rates between 4800 and 230400. I don't think it will work with higher baud rates than this. I also assume that there will be some output within 1 second (which is almost always the case with a GPS receiver).


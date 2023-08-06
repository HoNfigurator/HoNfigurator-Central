# System and infrastructure requirements
Your internet connection and CPU will make or break your HoN hosting career. 

## Internet connection
* 2 mbit/s _(up and down)_ **per** server instance
* You should have at least a Grade A BufferBloat test. Test Bufferbloat here: [Waveform BufferBloat test](https://www.waveform.com/tools/bufferbloat)
* You should have at most 100 ping against the region you wish to host. You can test ping against the entire world here: [World ping test](https://www.meter.net/tools/world-ping-test/)

## CPU & RAM
Each server instance requires at least 1 dedicated CPU thread with a **STR** *(Single Thread Rating)* of at atleast 1250 for best results.
Each instance takes 500-900 mb of ram, so make sure to account for all instances taking up at least 900MB when choosing total server count.
If you have a CPU with strong cores, you may run multiple game instances (up to 3) per thread. Recommended to start at 1 and work up.

### CPUs confirmed working with # instances

| CPU                    | Speed             | Cores | Threads | # Instances confirmed | STR  |
| ---------------------- | ----------------- |:-----:|:-------:|:---------------------:|:----:|
| Ryzen 5600x            | 3.7 GHz (4.6 GHz) | 6     | 12      | 24 (at 2 per Thread)                    | 3355 |
| intel Xeon E5-2650L V4 | 1.7 GHz (2.5 GHz) | 14    | 28      | 28                    | 1385 |
| Ryzen 1700             | 3.0 Ghz (3.7 Ghz) | 8     | 16      | 8                     | 1999 |
| intel i7-5930K         | 3.5 Ghz (3.7 Ghz) | 6     | 12      | 12                    | 2059 |


### Is your CPU not confirmed?

If the CPU isnt confirmed. You can confirm it by

1. Go to https://www.cpubenchmark.net/cpu.php and search for the CPU that is going to host the server
2. Make sure the _"Single Thread Rating"_ is above 1250. 
3. Report to tarrexd or kladze what your min max is

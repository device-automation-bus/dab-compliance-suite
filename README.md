# DAB Device Test #

This tool applies test cases for DAB enabled devices.

## Prerequisite ##
```
pip3 install -r requirements.txt
```

## Commands ##

These are the main commands of the tool:

```
<pre>$ python3 main.py --help
usage: main.py [-h] [-v] [-l] [-b BROKER] [-I ID] [-c CASE]

options:
  -h, --help            show this help message and exit
  -v, --verbose         increase output verbosity
  -l, --list            list the test cases
  -b BROKER, --broker BROKER
                        set the IP of the broker.Ex: -b 192.168.0.100
  -I ID, --ID ID        set the Device ID.Ex: -I mydevice123
  -c CASE, --case CASE  test only the specified case.Ex: -c 3
</pre>

```

## Command Examples ##

To list the command options:

```
# python3 main.py --help
```

To list the available test cases, type:

```
# python3 main.py -l
```

To execute the first test only:

```
# python3 main.py -v -b <your-box-ip> -I <device-id> -c 0
```

To execute the third test only:

```
# python3 main.py -v -b <your-box-ip> -I <device-id> -c 2
```

To execute all the tests:

```
# python3 main.py -v -b <your-box-ip> -I <device-id>
```
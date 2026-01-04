import serial.tools.list_ports_windows

ports = serial.tools.list_ports_windows.comports()
ports_info = {attr: getattr(ports[0], attr) for attr in dir(ports[0]) if not attr.startswith('_')}
for attr, value in ports_info.items():
    print(f"{attr}: {value}")
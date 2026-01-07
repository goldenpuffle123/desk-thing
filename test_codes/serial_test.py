import serial
import time

if __name__ == "__main__":
    ser = serial.Serial('COM3', 9600, timeout=0.1)
    time.sleep(2)
    
    while True:
        test = input("Enter input: ")
        if test == "exit":
            break
        ser.write((test+'\n').encode())
        start = time.time()
        while time.time() - start < 2:
            ret = ser.readline().decode(errors="ignore").strip()
            if ret:
                print(ret)
                break
    print("Done")
    ser.close()
    
import os
import time
from datetime import datetime

from typing import Any

from msgpackrpc import Address as RpcAddress, Client as RpcClient, error as RpcError
import sys
from ingeniamotion import MotionController
from os import path
from ingeniamotion.enums import CommutationMode, PhasingMode

# How long to wait in seconds between loop cycles
LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", 1))

# The M4 Proxy address needs to be mapped via Docker's extra hosts
M4_PROXY_ADDRESS = 'm4-proxy'
M4_PROXY_PORT =  5001
RPC_ADDRESS = RpcAddress(M4_PROXY_ADDRESS, M4_PROXY_PORT)
client = RpcClient(RPC_ADDRESS)


# Generate a single timestamp at the start of the program
TEST_START_TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H%M")
FILE_NAME = f"resultat_{TEST_START_TIMESTAMP}.txt"

def write_file(message):
    with open(FILE_NAME, "a") as file:
        file.write(message + "\n")
    print(f"File written to {FILE_NAME}")
# Display a message, log it, and send it to a remote display via RPC
def write_display(message):
    try:
        print(message)
        write_file(message)
        client.call("rpc_displaymessage", message)# Send message to display via RPC call
    except RpcError.TimeoutError:
        error_message = "Unable to retrieve  from the M4"
        print(error_message)
        write_file(error_message)
        

#connection to the drive
def connect_ethercat_drive(interface_name, slave_id, dict_path, mc, alias="servo1"):
    message = f"Starting test Connection for {alias} (dict={dict_path}, slave_id={slave_id}, interface={interface_name})"
    write_display(message)

   
    mc.communication.connect_servo_ethercat(
            interface_name=interface_name,
            slave_id=slave_id,
            dict_path=dict_path,
            alias=alias
        )
    success_msg = f"Success: [{alias}] EtherCAT connection established."
    write_display(success_msg)
       
    write_display(f"Test ended for {alias}.")
   

def read_drive_voltage(mc, alias, register):
    voltage = mc.communication.get_register(register, alias, 1)
    if voltage is None:
        raise Exception("Error :Unable to read voltage")
    return voltage


def validate_value_voltage(voltage):
    message = f"Validating voltage ({voltage:.2f} V)"
    write_display(message)
    #Condition to start running the tests
    if voltage < 46:
       raise ValueError(
            f"Invalid voltage to begin testing: measured value is {voltage:.2f} V (must be ≥ 46 V)." )
    success_msg = "Voltage is valid for testing."
    write_display(success_msg)

#Verification tests
def safety_checker(mc,alias):
    message = f"Starting test: safety_checker for {alias}"
    write_display(message)

    result=mc.tests.sto_test(alias,1)
    if  result["result_severity"] == 0:
        message = f"Success: STO active"
        write_display(message)     
    else:
         raise Exception("Error : STO test failed.please check the suggested registers") 

    write_display(f"Test ended  for {alias}.")

def check_encoder_configuration(mc, alias):
    # Start the test to check absolute encoder configuration
    message = f"Starting test: check_encoder_configuration  for {alias}"
    write_display(message)
   

    # Run the encoder test without applying automatic changes
    # This checks if the absolute encoder is correctly configured for axis 1
    result = mc.tests.absolute_encoder_1_test(alias, axis=1, apply_changes=False)
    write_display(f"Result: {result}")

    # If no issue is detected (result_severity == 0), the test is successful
    if result["result_severity"] == 0:
       message = f"Success: Test"
       write_display(message)
    else:
        # If an issue is found, raise an exception with suggested register corrections
        raise Exception(f"Error : Encoder configuration test unsuccessful. Details: {result}") # la meme chose 

    # End of the test
    write_display(f"Test ended  for {alias}.")
   

def start_test(mc, alias, activated, release): # changer le nom 
    if release:
        mc.configuration.release_brake(alias, 1)
    else:
        mc.configuration.enable_brake(alias, 1)

    if activated:
        mc.motion.motor_enable(alias, 1) 
    else:
        mc.motion.motor_disable(alias, 1) 

def to_modify_current(mc, alias, register, values):
    mc.communication.set_register(register, values, alias, 1)
    write_display(f"Current value updated: current value is {values} ") # # add the modified current value


def perform_commutation_and_check_phasing(mc, alias):
     # Start the test to check phasing
    message = f"Starting test: phasing test {alias}"
    write_display(message)
 
    #Set phasing mode to 2: no phasing
    mc.configuration.set_phasing_mode(2, alias, axis=1)
    #Deactivate the motor and release the brake
    start_test(mc, alias, False, True)
   
    result1 = mc.tests.commutation(alias, 1, False)
    write_display(f"Commutation test result: {result1}")
    if result1["result_severity"] == 0:
        write_display("Success")
        angle_offset = result1["suggested_registers"].get("COMMU_ANGLE_OFFSET", None)
        if angle_offset is not None:
            write_display(f"Value of angle offset: {angle_offset}")
            #Update the angle value in the appropriate register
            mc.communication.set_register("COMMU_ANGLE_OFFSET", angle_offset, alias)

        result2 = mc.tests.phasing_check(alias, 1)
        write_display(f"Phasing test result: {result2}")
        if result2["result_severity"] == 0:
            message = f"Success: Test"
            write_display(message)
        else:
            raise Exception(" Error : Phasing check failed: Check the suggested registers.")
    else:
        raise Exception ("Error : Commutation test failed: Check the suggested registers.")

    write_display(f"Test ended  for {alias}.")


def test_brake(mc, alias, register, value, velocity, current_max, duration):
    # Start the test to check phasing
    message = f"Starting test: brake {alias}"
    write_display(message)
    # Modify the current limit to protect the hardware during the brake test
    to_modify_current(mc, alias, register, value)

    # Enable the motor and engage the brake (True for enable, False to keep brake applied)
    start_test(mc, alias, True, False)

    # Set operation mode to velocity mode (mode 3)
    mc.motion.set_operation_mode(3, alias, 1)

    # Send a velocity command while the brake is applied
    mc.motion.set_velocity(velocity, alias, 1, False, False)

    # Wait for a short duration to observe if the motor moves
    time.sleep(duration)

    actual_velocity = mc.motion.get_actual_velocity(alias, 1)
    actual_current=mc.motion.get_actual_current_quadrature(alias,1)

    # Check if the brake held the motor stationary
    if abs(actual_velocity) < 0.5 and actual_current > 0.9 * value:
        write_display("Success: The motor remained locked. Brake OK.")
    else:
        raise Exception(f"Error : The motor moved! Measured velocity: {actual_velocity}! Measured current {actual_current}")

    # Stop the motor and reset brake configuration
    mc.motion.set_velocity(0, alias, 1, False, False)
    mc.motion.motor_disable(alias, 1)
    mc.configuration.default_brake(alias, 1)

    # Restore the original current limit after the test
    to_modify_current(mc, alias, register, current_max)

    write_display(f"Test ended  for {alias}.")

def return_to_center(mc, velocity, alias, mode):
    pos_raw = mc.motion.get_actual_position(alias, 1)
      # Convert raw position to degrees
    encoder_resolution =360 / 2009497.6
    pos_deg = pos_raw * encoder_resolution

    

    timeout = time.time() + 15
    error = float('inf')
    # Determine center target based on the selected mode
    if mode == "detect and return":
       # Set the mechanical limit detection angle
        offset = 107 if velocity > 0 else -107
        target_center_deg = pos_deg - offset
        write_file(f"Start return to center from {pos_deg:.2f}°, target: {target_center_deg:.2f}°")
    elif mode == "return":
        target_center_deg = 0
    else:
        write_file(f"Unknown mode: {mode}")
        return False

    while abs(error) > 0.5 and time.time() < timeout:
        pos_raw = mc.motion.get_actual_position(alias, 1)
        pos_deg = pos_raw *encoder_resolution
        error = pos_deg - target_center_deg

        #write_file(f"Current position: {pos_deg:.2f}°, error: {error:.4f}°")
        # Set movement direction based on the error sign
        direction = -1 if error > 0 else 1
        command = direction * abs(velocity)
        mc.motion.set_velocity(command, alias, 1, True, False)
   #Stop the motor
    mc.motion.set_velocity(0, alias, 1, False, True)

    if abs(error) <= 0.5:
        write_display("Exact position reached. Center set.")
        return True
    else:
        write_file("Timeout reached. Return to center not completed.")
        return False
def detect_limit(mc, current_velocity, velocity, alias, current, current_compare):
    # Log the current velocity, measured current, and nominal current threshold
   
    write_file(f"Current velocity: {current_velocity}, Measured current: {current}, Threshold: {current_compare}")

    # Detect mechanical limit: motor stopped and current exceeds nominal threshold
    if current_velocity == 0 and abs(current) > current_compare:
        write_display(" limit detected.")
        return_to_center(mc, velocity, alias, "detect and return")
        time.sleep(5)
        return True
    else:
        write_display("No limit detected.")
        return False
def test_velocity(mc, alias, velocity_MAX, specified_current, test_time, velocity_list, nominal_current,type_de_moteur):
   

    for test_name, velocity in velocity_list.items():
        write_display(f"Starting {test_name} at velocity {velocity}")

        start_test(mc, alias, True, True)
        time.sleep(0.2)

        velocity_total = 0
        current_total = 0
        count = 0

        mc.motion.set_operation_mode(3, alias, 1)
        time.sleep(0.1)
        mc.motion.target_latch(alias, 1)
        time.sleep(0.1)
        mc.motion.set_velocity(velocity, alias, 1, True, False)

        # Start global timer
        start_time = time.time()

        # Passive wait until t = 2s
        while time.time() - start_time < 2:
            time.sleep(0.01)

        # Measurements from t = 2s until test_time
        while time.time() - start_time < test_time:
            velocity_i = mc.motion.get_actual_velocity(alias, 1)
            current_i = mc.motion.get_actual_current_quadrature(alias, 1)

            velocity_total += velocity_i
            current_total += current_i
            count += 1
            time.sleep(1)

        # Calculate averages
        velocity_avg = velocity_total / count if count > 0 else 0
        current_avg = current_total / count if count > 0 else 0

        velocity_min = velocity - 0.1 * velocity_MAX
        velocity_max = velocity + 0.1 * velocity_MAX
        current_min = specified_current - 0.1 * nominal_current
        current_max = specified_current + 0.1 * nominal_current

     
        write_display(f" Target speed:{velocity}, Average velocity: {velocity_avg:.2f}, Expected: [{velocity_min:.2f}, {velocity_max:.2f}]")
        write_display(f" Average current: {current_avg:.2f}, Expected: [{current_min:.2f}, {current_max:.2f}]")

        if not (velocity_min < velocity_avg < velocity_max):
            raise Exception(f"Velocity test failed for {test_name}")
            

        if not (current_min < current_avg < current_max):
            raise Exception(f"Current test failed for {test_name}")
            
        if type_de_moteur=="direction":
            return_to_center(mc, velocity, alias, "return")
        mc.motion.set_velocity(0, alias, 1, False, True)
        time.sleep(5)
        write_display(f"Test completed for {test_name}")
   
    

def test_motor_no_load(mc, alias, type_de_moteur, register, velocity_MAX, specified_current,
                       temps_test, velocity_list, current_compare, current_max,
                       nominal_current, velocity, values):
    message = f"Starting test: motor no load  {alias}"
    write_display(message)
    to_modify_current(mc, alias, register, values)

    #Enable motor + release brake
    start_test(mc, alias, True, True)
    time.sleep(0.1)

    mc.motion.set_operation_mode(3, alias, 1)
    time.sleep(0.1)

    mc.motion.target_latch(alias, 1)
    time.sleep(0.1)

    if type_de_moteur == "direction":
        mc.motion.set_velocity(velocity, alias, 1, True, False)
        timeout = time.time() + 50  

        while True:
            current_velocity = mc.motion.get_actual_velocity(alias, 1)
            current = mc.motion.get_actual_current_quadrature(alias, 1)

            if detect_limit(mc, current_velocity, velocity, alias, current, current_compare):
                break
            if time.time() > timeout:
                write_display("Timeout reached while waiting for limit detection.")
                break


            time.sleep(0.1)  
    else:
        
        mc.motion.set_velocity(velocity, alias, 1, True, False)
        time.sleep(2)

   
    test_velocity(mc, alias, velocity_MAX, specified_current, temps_test, velocity_list, nominal_current,type_de_moteur)

    
    to_modify_current(mc, alias, register, current_max)

   
    start_test(mc, alias, False, False)
    write_display(f"Test ended  for {alias}.")


def disconnect(mc,alias):
    start_test(mc,alias,False,True)
    mc.communication.disconnect(alias)
    write_display("Drive is disconnected.")
   
def run_motor_tests(mc, alias, slave_id, dict_path, register_name, register, values, velocity_MAX,
                    specified_current, temps_test, velocity_list, current_compare,
                    nominal_current, velocity, current_max, brake_test_duration, type_de_moteur,
                    do_brake_test, do_phasing=True, do_no_load_test=True):


    interface_name = r"\Device\NPF_{4CDAA26F-28E1-455B-8DF1-B924D87BCCAD}"
    try:
            connect_ethercat_drive(interface_name, slave_id=slave_id, dict_path=dict_path, mc=mc, alias=alias)
        
            voltage = read_drive_voltage(mc, alias=alias, register=register_name)

            
            validate_value_voltage(voltage)
            safety_checker(mc=mc, alias=alias)  

            if do_phasing:
                        check_encoder_configuration(mc, alias)
                        start_test(mc, alias, activated=False, release=True)
                        perform_commutation_and_check_phasing(mc, alias)

            if do_brake_test:
                       test_brake(mc, alias, register, values, velocity ,current_max, brake_test_duration)

            if do_no_load_test:
                        test_motor_no_load(mc=mc, alias=alias, type_de_moteur=type_de_moteur, register=register,
                                           velocity_MAX=velocity_MAX, specified_current=specified_current,
                                           temps_test=temps_test, velocity_list=velocity_list,
                                           current_compare=current_compare, current_max=current_max,
                                           nominal_current=nominal_current, velocity=velocity, values=values)

            position = mc.motion.get_actual_position(alias, 1) * 360 / 2009497.6
            write_display(f"[{alias}] Position finale : {position:.2f}°")
    except Exception as e:
            write_display(f"Error during test for {alias}: {e}")
    
    finally:
            disconnect(mc, alias)
  
  

def main():
    mc = MotionController()
    register_name = "DRV_PROT_VBUS_VALUE"
    register = "CL_CUR_REF_MAX"
    dict_path = r"C:\Users\Salma Bouazzaoui\Desktop\k2-mro-e_eoe_1_2.6.0.xdf"

    run_motor_tests(
        mc=mc,
        alias="servo2",
        slave_id=2,
        dict_path=dict_path,
        register_name=register_name,
        register=register,
        values=2.2,
        velocity_MAX=20,
        specified_current=2,
        temps_test=8,
        velocity_list={
            "test1": 5,
            "test2": -5,
            "test3": 8,
            "test4": -8,
            "test5": 10,
            "test6": -10
        },
       current_compare=3,
       nominal_current=44,
       velocity=4,
       current_max=115,
       brake_test_duration=5,
       type_de_moteur="traction",
        do_brake_test=True
   )
    write_display("Waiting for servo2 to come to a complete stop...")
    time.sleep(10)


    run_motor_tests(
        mc=mc,
        alias="servo1",
        slave_id=1,
        dict_path=dict_path,
        register_name=register_name,
        register=register,
        values=1,
        velocity_MAX=40,
        specified_current=0.8,
        temps_test=4,
        velocity_list={
            "test1": -10,
            "test2": 10,
            "test3": -13,
            "test4": 13
        },
        current_compare=1,
        nominal_current=15.51,
        velocity=10,
        current_max=32.23,
        brake_test_duration=2,
        type_de_moteur="direction",
        do_brake_test=False
    )
    write_display("Waiting for servo2 to come to a complete stop...")
    time.sleep(10)


    run_motor_tests(
        mc=mc,
        alias="servo1",
        slave_id=1,
        dict_path=dict_path,
        register_name=register_name,
        register=register,
        values=1,
        velocity_MAX=40,
        specified_current=0.8,
        temps_test=4,
        velocity_list={
            "test1": -10,
            "test2": 10,
            "test3": -13,
            "test4": 13
        },
        current_compare=1,
        nominal_current=15.51,
        velocity=-10,
        current_max=32.23,
        brake_test_duration=2,
        type_de_moteur="direction",
        do_brake_test=False
    )


    write_display("Final direction test for servo1 completed.")

    

   
if __name__ == "__main__":
    main()
  
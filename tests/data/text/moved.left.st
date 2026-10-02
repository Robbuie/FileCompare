PROGRAM Conveyor
VAR
    Start_PB    : BOOL;
    Stop_PB     : BOOL;
    Motor_Run   : BOOL;
    Run_Timer   : TON;
    Jam_Count   : INT;
END_VAR

(* Fault handling *)
IF Jam_Sensor AND Motor_Run THEN
    Jam_Count := Jam_Count + 1;
    Motor_Run := FALSE;
END_IF;

(* Start and stop *)
IF Start_PB AND NOT Stop_PB THEN
    Motor_Run := TRUE;
END_IF;
IF Stop_PB THEN
    Motor_Run := FALSE;
END_IF;

Run_Timer(IN := Motor_Run, PT := T#5S);
Belt_Speed := 120;
END_PROGRAM

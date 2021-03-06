from typing import List

from magicbot import feedback, tunable
import ctre
import wpilib


class Indexer:
    intake_main_motor: ctre.WPI_TalonSRX
    indexer_motors: List[ctre.WPI_TalonSRX]
    injector_motor: ctre.WPI_TalonSRX
    piston_switch: wpilib.DigitalInput

    intake_arm_piston: wpilib.Solenoid
    intake_left_motor: wpilib.interfaces.SpeedController  # Looking from behind the robot
    intake_right_motor: wpilib.interfaces.SpeedController  # Looking from behind the robot

    indexer_speed = tunable(0.6)
    injector_speed = tunable(0.7)
    intake_motor_speed = tunable(1.0)
    shimmy_speed = tunable(1.0)
    shimmy_ticks = tunable(int(50 * 0.25))

    intake_lowered = tunable(False)
    intaking = tunable(False)
    shimmying = tunable(False)

    def __init__(self):
        self.clearing = False

    def setup(self):
        # All the motors that comprise indexer cells, in order from intake
        self.all_motors: List[ctre.WPI_TalonSRX] = [self.intake_main_motor]
        self.all_motors.extend(self.indexer_motors)
        self.all_motors.append(self.injector_motor)

        for motor in self.all_motors:
            motor.setInverted(True)
            motor.setNeutralMode(ctre.NeutralMode.Brake)
            motor.configForwardLimitSwitchSource(
                ctre.LimitSwitchSource.FeedbackConnector,
                ctre.LimitSwitchNormal.NormallyOpen,
            )

        self.intake_left_motor.setInverted(False)
        self.intake_right_motor.setInverted(True)

        self.intake_main_motor.setInverted(False)
        self.injector_motor.setInverted(False)
        self.indexer_motors[1].setInverted(False)

        # We have a delay because the distance between the second last
        # stage of the indexer and the injector is longer than others
        # and the injector motors are slower
        self.transfer_to_injector = False
        self.left_shimmy = True

        self.shimmy_count = 0

    def on_enable(self) -> None:
        self.shimmy_count = 0
        self.intaking = False
        self.intake_lowered = False
        self.clearing = False

    def execute(self) -> None:
        if self.clearing:
            # Run everything backwards to try to clear a jam
            for motor in self.indexer_motors:
                motor.set(-self.indexer_speed)
            self.intake_left_motor.set(0)
            self.intake_right_motor.set(0)
            return

        if self.intaking:
            injector = self.injector_motor
            feeder = self.indexer_motors[-1]
            intake_main_motor = self.intake_main_motor

            if injector.isFwdLimitSwitchClosed():
                self.transfer_to_injector = False
            elif feeder.isFwdLimitSwitchClosed():
                # Transferring
                self.transfer_to_injector = True

            # Turn on all motors and let the limit switches stop it
            intake_main_motor.set(self.intake_motor_speed)
            for motor in self.indexer_motors:
                motor.set(self.indexer_speed)
            if self.is_piston_retracted():
                injector.set(self.injector_speed)
            else:
                feeder.stopMotor()
                injector.stopMotor()

            # Override any limit switches where the next cell is vacant
            for first, second in zip(self.all_motors, self.all_motors[1:]):
                at_limit = second.isFwdLimitSwitchClosed()
                if second == feeder and self.transfer_to_injector:
                    at_limit = True  # Pretend the ball is still in the feeder
                if not at_limit:
                    first.overrideLimitSwitchesEnable(False)
                else:
                    first.overrideLimitSwitchesEnable(True)

            if not intake_main_motor.isFwdLimitSwitchClosed():
                if self.shimmying:
                    if self.left_shimmy:
                        self.intake_left_motor.set(self.shimmy_speed)
                        self.intake_right_motor.set(0)
                        self.shimmy_count += 1
                        if self.shimmy_count > self.shimmy_ticks:
                            self.left_shimmy = False
                            self.shimmy_count = 0
                    else:
                        self.intake_left_motor.set(0)
                        self.intake_right_motor.set(self.shimmy_speed)
                        self.shimmy_count += 1
                        if self.shimmy_count > self.shimmy_ticks:
                            self.left_shimmy = True
                            self.shimmy_count = 0
                else:
                    self.intake_left_motor.set(self.shimmy_speed)
                    self.intake_right_motor.set(self.shimmy_speed)

            else:
                self.intake_right_motor.set(0)
                self.intake_left_motor.set(0)
        else:
            self.intake_left_motor.set(0)
            self.intake_right_motor.set(0)

            # Move balls through if we have them, but don't take in more
            ball_in_previous = False
            for motor in self.all_motors:
                if not motor.isFwdLimitSwitchClosed():
                    # We don't have a ball in this cell
                    # Test this first so the previous ball flag works
                    if not ball_in_previous:
                        motor.stopMotor()
                else:
                    ball_in_previous = True
                motor.stopMotor()

        if self.intake_lowered:
            self.intake_arm_piston.set(True)
        else:
            self.intake_arm_piston.set(False)

    def enable_intaking(self) -> None:
        self.intaking = True

    def disable_intaking(self) -> None:
        self.intaking = False

    def raise_intake(self) -> None:
        self.intake_lowered = False

    def lower_intake(self) -> None:
        self.intake_lowered = True

    @feedback
    def balls_loaded(self) -> int:
        balls = sum(motor.isFwdLimitSwitchClosed() for motor in self.all_motors)
        return balls

    def is_piston_retracted(self) -> bool:
        return not self.piston_switch.get()

    @feedback
    def is_ready(self) -> bool:
        return (
            self.injector_motor.isFwdLimitSwitchClosed() and self.is_piston_retracted()
        )

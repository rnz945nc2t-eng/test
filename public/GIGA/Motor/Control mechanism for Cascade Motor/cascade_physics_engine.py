"""
CASCADE MOTOR PHYSICS ENGINE
============================

Physics-based calculations for the Cascaded Impulse-Augmented Multi-Motor
Torque Cascade System. Provides detailed modeling of:

✓ Torque calculations with impulse effects
✓ Energy flow and efficiency tracking
✓ Capacitor charging/discharging dynamics
✓ Thermal management
✓ Back-EMF generation and harvesting
✓ Impulse timing optimization
"""

import math
from dataclasses import dataclass
from typing import Tuple, List
from enum import Enum


# ==============================================================================
# PHYSICS CONSTANTS & MODELS
# ==============================================================================

@dataclass
class MotorPhysics:
    """Physical parameters for motor stages."""
    
    # Electrical properties
    phase_resistance: float = 0.5      # Ohms
    phase_inductance: float = 0.001    # Henry
    
    # Mechanical properties
    pole_pairs: int = 4                # Number of pole pairs
    back_emf_constant: float = 0.1     # Vs/rad (Ke)
    torque_constant: float = 0.1       # Nm/A (Kt)
    
    # Thermal properties
    thermal_capacity: float = 100.0    # J/°C
    cooling_rate: float = 5.0          # W/°C
    
    # Efficiency factors
    friction_coefficient: float = 0.02 # Normalized friction
    core_loss_percent: float = 0.03    # 3% core losses


@dataclass
class CapacitorBank:
    """High-voltage capacitor bank properties."""
    
    capacitance: float = 0.1            # Farads (100mF)
    max_voltage: float = 100.0          # Volts
    esr: float = 0.01                   # Equivalent Series Resistance (Ohms)
    energy_stored_joules: float = 0.0   # Current energy
    
    def stored_energy(self, voltage: float) -> float:
        """Calculate stored energy: E = 0.5 * C * V²."""
        return 0.5 * self.capacitance * (voltage ** 2)
    
    def peak_discharge_current(self, target_voltage: float) -> float:
        """Peak discharge current through ESR."""
        voltage_diff = self.max_voltage - target_voltage
        return voltage_diff / self.esr


# ==============================================================================
# TORQUE CALCULATIONS
# ==============================================================================

class TorqueCalculator:
    """Calculates torque for cascade motor stages."""
    
    @staticmethod
    def mechanical_coupling_torque(
        previous_stage_torque: float,
        coupling_fraction: float
    ) -> float:
        """Torque from mechanical coupling with upstream stage."""
        return previous_stage_torque * coupling_fraction
    
    @staticmethod
    def independent_power_torque(
        current_amps: float,
        torque_constant: float
    ) -> float:
        """Torque from independent motor supply."""
        return current_amps * torque_constant
    
    @staticmethod
    def impulse_torque(
        capacitor_bank: CapacitorBank,
        capacitor_voltage: float,
        torque_constant: float,
        efficiency: float = 0.85
    ) -> float:
        """Torque from capacitor impulse discharge.
        
        The impulse creates a magnetic spike that produces torque.
        Energy from capacitor is converted to mechanical work.
        """
        # Peak discharge current
        peak_current = capacitor_bank.peak_discharge_current(0.1 * capacitor_bank.max_voltage)
        
        # Impulse duration (very brief, milliseconds)
        impulse_duration = 0.002  # 2ms
        
        # Average current during impulse
        avg_current = peak_current * 0.5 * impulse_duration
        
        # Torque contribution (pulsed)
        return avg_current * torque_constant * efficiency
    
    @staticmethod
    def total_stage_torque(
        previous_torque: float,
        coupling_fraction: float,
        stage_current: float,
        torque_constant: float,
        capacitor_impulse: float = 0.0
    ) -> float:
        """Total torque at a stage.
        
        τ_k = f_k · τ_{k-1} + τ_indep,k + Δτ_impulse,k-1
        
        Where:
        - f_k = mechanical coupling fraction
        - τ_{k-1} = torque from previous stage
        - τ_indep,k = torque from independent power supply
        - Δτ_impulse,k-1 = torque from capacitor impulse
        """
        mechanical = TorqueCalculator.mechanical_coupling_torque(
            previous_torque, coupling_fraction
        )
        independent = TorqueCalculator.independent_power_torque(
            stage_current, torque_constant
        )
        
        return mechanical + independent + capacitor_impulse


# ==============================================================================
# ENERGY FLOW CALCULATIONS
# ==============================================================================

class EnergyCalculator:
    """Calculates energy flow and efficiency throughout system."""
    
    @staticmethod
    def electrical_power_input(voltage: float, current: float) -> float:
        """Electrical power supplied to motor."""
        return voltage * current
    
    @staticmethod
    def mechanical_power_output(torque: float, omega_rad_s: float) -> float:
        """Mechanical power output: P = τ · ω."""
        return torque * omega_rad_s
    
    @staticmethod
    def back_emf(back_emf_constant: float, omega_rad_s: float) -> float:
        """Back-EMF generated by rotating motor: e = Ke · ω."""
        return back_emf_constant * omega_rad_s
    
    @staticmethod
    def copper_loss(
        phase_resistance: float,
        current: float,
        num_phases: int = 3
    ) -> float:
        """I²R losses in motor windings."""
        return num_phases * (current ** 2) * phase_resistance
    
    @staticmethod
    def friction_loss(
        friction_coefficient: float,
        torque: float,
        omega_rad_s: float
    ) -> float:
        """Friction losses from mechanical resistance."""
        return friction_coefficient * torque * omega_rad_s
    
    @staticmethod
    def total_losses(
        phase_resistance: float,
        current: float,
        torque: float,
        omega_rad_s: float,
        core_loss_percent: float = 0.03
    ) -> float:
        """Total losses in motor."""
        copper = EnergyCalculator.copper_loss(phase_resistance, current)
        friction = EnergyCalculator.friction_loss(0.02, torque, omega_rad_s)
        core = copper * core_loss_percent  # Core losses as percent of copper loss
        
        return copper + friction + core
    
    @staticmethod
    def stage_efficiency(
        power_output: float,
        power_input: float,
        losses: float
    ) -> float:
        """Stage efficiency percentage."""
        if power_input == 0:
            return 0.0
        efficiency = (power_output / power_input) * 100
        return min(efficiency, 100.0)
    
    @staticmethod
    def cascade_efficiency(
        stage_efficiencies: List[float]
    ) -> float:
        """Overall cascade efficiency (product of all stages)."""
        overall = 1.0
        for eff in stage_efficiencies:
            overall *= (eff / 100.0)
        return overall * 100.0


# ==============================================================================
# CAPACITOR CHARGING DYNAMICS
# ==============================================================================

class CapacitorDynamics:
    """Simulates capacitor charging and discharging."""
    
    @staticmethod
    def charge_voltage_from_back_emf(
        back_emf: float,
        capacitor_voltage: float,
        dt: float,
        charge_efficiency: float = 0.95
    ) -> float:
        """Update capacitor voltage from back-EMF (charging).
        
        The back-EMF charges the capacitor through a rectifier/boost circuit.
        """
        if back_emf <= capacitor_voltage:
            return capacitor_voltage  # Can't charge if back-EMF is lower
        
        # Energy transfer rate limited by circuit
        energy_in = back_emf * charge_efficiency * dt
        return min(capacitor_voltage + energy_in * 0.5, 100.0)  # Max 100V
    
    @staticmethod
    def discharge_capacitor(
        capacitor: CapacitorBank,
        target_voltage: float,
        discharge_time: float = 0.002
    ) -> Tuple[float, float]:
        """Discharge capacitor to motor.
        
        Returns:
            (new_voltage, energy_released)
        """
        voltage_drop = capacitor.max_voltage - target_voltage
        if voltage_drop <= 0:
            return target_voltage, 0.0
        
        # Peak discharge current limited by ESR
        peak_current = voltage_drop / capacitor.esr
        
        # Energy released (simplified exponential decay)
        energy_released = capacitor.stored_energy(capacitor.max_voltage) * 0.8
        
        # New voltage after discharge
        new_voltage = target_voltage
        
        return new_voltage, energy_released
    
    @staticmethod
    def optimal_impulse_timing(
        target_rpm: float,
        actual_rpm: float,
        pole_pairs: int = 4
    ) -> float:
        """Calculate optimal impulse timing relative to rotor alignment.
        
        Returns timing in milliseconds when impulse should fire.
        """
        # Convert RPM to electrical frequency
        freq_hz = (actual_rpm / 60.0) * pole_pairs
        
        # One electrical cycle
        cycle_time_ms = 1000.0 / max(freq_hz, 1.0)
        
        # Fire when rotor is aligned (90 degrees of phase)
        optimal_time = cycle_time_ms * 0.25
        
        return optimal_time


# ==============================================================================
# RPM & SPEED DYNAMICS
# ==============================================================================

class SpeedDynamics:
    """Simulates motor speed changes."""
    
    @staticmethod
    def rpm_from_torque(
        torque: float,
        load_torque: float,
        inertia: float,
        dt: float
    ) -> float:
        """Calculate RPM change from net torque.
        
        τ_net = τ_motor - τ_load = I · α
        α = Δω/Δt
        """
        net_torque = torque - load_torque
        angular_accel = net_torque / inertia  # rad/s²
        delta_omega = angular_accel * dt     # rad/s
        
        # Convert to RPM change
        delta_rpm = (delta_omega * 60.0) / (2 * math.pi)
        
        return delta_rpm
    
    @staticmethod
    def angular_velocity_rad_s(rpm: float) -> float:
        """Convert RPM to angular velocity in rad/s."""
        return (rpm * 2 * math.pi) / 60.0


# ==============================================================================
# THERMAL MANAGEMENT
# ==============================================================================

class ThermalModel:
    """Thermal calculations for motor stages."""
    
    @staticmethod
    def temperature_rise(
        power_loss: float,
        thermal_capacity: float,
        dt: float
    ) -> float:
        """Temperature rise from power losses.
        
        dT = P_loss * dt / C_thermal
        """
        if thermal_capacity == 0:
            return 0.0
        return (power_loss * dt) / thermal_capacity
    
    @staticmethod
    def cooling_effect(
        current_temp: float,
        ambient_temp: float,
        cooling_rate: float,
        dt: float
    ) -> float:
        """Cooling from ambient environment."""
        temp_diff = current_temp - ambient_temp
        if temp_diff <= 0:
            return 0.0
        
        # Newton's law of cooling
        cooling = cooling_rate * temp_diff * dt
        return cooling
    
    @staticmethod
    def new_temperature(
        current_temp: float,
        power_loss: float,
        thermal_capacity: float,
        ambient_temp: float,
        cooling_rate: float,
        dt: float
    ) -> float:
        """Calculate new temperature after time step."""
        rise = ThermalModel.temperature_rise(power_loss, thermal_capacity, dt)
        cooling = ThermalModel.cooling_effect(current_temp, ambient_temp, cooling_rate, dt)
        
        new_temp = current_temp + rise - cooling
        return max(new_temp, ambient_temp)


# ==============================================================================
# MODE-SPECIFIC CALCULATIONS
# ==============================================================================

class ModeCalculations:
    """Physics-based calculations for each operating mode."""
    
    @staticmethod
    def fast_mode_torque_profile(stage_id: int, num_stages: int) -> float:
        """Torque scaling for Fast mode.
        
        Prioritizes speed, so later stages have lower torque multipliers.
        """
        return 0.7 + (stage_id * 0.06)
    
    @staticmethod
    def climbing_mode_torque_profile(stage_id: int, num_stages: int) -> float:
        """Torque scaling for Climbing mode.
        
        Maximizes torque multiplication, especially at output stages.
        """
        return 0.5 + (stage_id * 0.1)
    
    @staticmethod
    def efficiency_mode_scaling(stage_id: int) -> float:
        """Power scaling for Efficiency mode.
        
        Minimizes overall power draw while maintaining sufficient output.
        """
        return 0.3 + (stage_id * 0.08)
    
    @staticmethod
    def calculate_load_adaptive_coupling(
        load_fraction: float,
        stage_id: int,
        base_coupling: float
    ) -> float:
        """Adjust coupling fraction based on load.
        
        Under high load, reduce input stage coupling to prevent stall.
        """
        if load_fraction > 0.8:
            # High load: reduce coupling to keep input stage spinning
            reduction = 0.5 - (load_fraction * 0.3)
            return base_coupling * reduction
        else:
            return base_coupling


# ==============================================================================
# SYSTEM SIMULATION & ANALYSIS
# ==============================================================================

def analyze_cascade_stages(num_stages: int = 5, load_fraction: float = 0.5):
    """Analyze torque and efficiency through cascade stages."""
    
    print("\n" + "="*100)
    print("CASCADE MOTOR PHYSICS ANALYSIS")
    print("="*100)
    
    # Initialize physics
    motor_physics = MotorPhysics()
    capacitor = CapacitorBank()
    
    # Simulation parameters
    current = 30.0  # Amps
    rpm = 8000.0
    omega = SpeedDynamics.angular_velocity_rad_s(rpm)
    load_torque = 50.0 * load_fraction
    
    print(f"\nInitial Conditions:")
    print(f"  Input RPM: {rpm:.0f}")
    print(f"  Input Current: {current:.1f}A")
    print(f"  Load Torque: {load_torque:.2f}Nm")
    print(f"  Load Fraction: {load_fraction:.1f}")
    
    print(f"\n{'Stage':<8} {'Torque (Nm)':<15} {'Power (W)':<15} {'Efficiency':<15} {'Back-EMF (V)':<15}")
    print(f"{'-'*80}")
    
    previous_torque = 0.0
    stage_efficiencies = []
    
    for stage_id in range(num_stages):
        # Calculate back-EMF
        back_emf = EnergyCalculator.back_emf(motor_physics.back_emf_constant, omega)
        
        # Coupling fraction (increases down cascade)
        coupling_fraction = 0.05 + (stage_id * 0.15)
        
        # Calculate torque components
        mechanical_torque = TorqueCalculator.mechanical_coupling_torque(
            previous_torque, coupling_fraction
        )
        independent_torque = TorqueCalculator.independent_power_torque(
            current, motor_physics.torque_constant
        )
        
        # Capacitor impulse
        capacitor_voltage = 50.0 + stage_id * 10
        impulse_torque = TorqueCalculator.impulse_torque(
            capacitor, capacitor_voltage, motor_physics.torque_constant
        )
        
        # Total torque
        total_torque = mechanical_torque + independent_torque + impulse_torque
        
        # Power calculations
        power_in = EnergyCalculator.electrical_power_input(48.0, current)
        power_out = EnergyCalculator.mechanical_power_output(total_torque, omega)
        
        # Losses
        losses = EnergyCalculator.total_losses(
            motor_physics.phase_resistance,
            current,
            total_torque,
            omega,
            motor_physics.core_loss_percent
        )
        
        # Efficiency
        efficiency = EnergyCalculator.stage_efficiency(power_out, power_in, losses)
        stage_efficiencies.append(efficiency)
        
        # RPM reduction through cascade (simplified)
        rpm = rpm * (0.75 - stage_id * 0.08)
        omega = SpeedDynamics.angular_velocity_rad_s(rpm)
        
        print(f"Stage {stage_id:<2} {total_torque:>12.2f}   {power_out:>12.2f}   "
              f"{efficiency:>12.1f}%   {capacitor_voltage:>12.1f}")
        
        previous_torque = total_torque
    
    # Overall cascade analysis
    cascade_eff = EnergyCalculator.cascade_efficiency(stage_efficiencies)
    
    print(f"\n{'='*100}")
    print(f"CASCADE SUMMARY:")
    print(f"  Individual Stage Efficiencies: {[f'{e:.1f}%' for e in stage_efficiencies]}")
    print(f"  Overall Cascade Efficiency: {cascade_eff:.1f}%")
    print(f"  Output Torque Multiplication: {total_torque / (30.0 * motor_physics.torque_constant):.2f}x")
    print(f"{'='*100}\n")


def thermal_analysis():
    """Analyze thermal behavior under different operating conditions."""
    
    print("\n" + "="*100)
    print("THERMAL ANALYSIS - TEMPERATURE EVOLUTION OVER TIME")
    print("="*100)
    
    motor_physics = MotorPhysics()
    
    # Scenario: continuous high load
    power_loss = 500.0  # Watts
    initial_temp = 25.0  # Ambient
    dt = 1.0  # Time step in seconds
    
    print(f"\nScenario: {power_loss}W continuous loss, 1°C/s simulation")
    print(f"{'Time (s)':<12} {'Temp (°C)':<12} {'Cooling (W)':<15} {'Rate (°C/s)':<15}")
    print(f"{'-'*60}")
    
    temps = []
    for t in range(0, 600, 10):  # 10 minutes
        cooling = motor_physics.cooling_rate * (initial_temp - 25.0)
        new_temp = ThermalModel.new_temperature(
            initial_temp,
            power_loss,
            motor_physics.thermal_capacity,
            25.0,  # Ambient
            motor_physics.cooling_rate,
            dt * 10
        )
        
        rate = (new_temp - initial_temp) / (dt * 10)
        
        print(f"{t:<12} {new_temp:>10.1f}°C  {cooling:>13.1f}W  {rate:>13.2f}°C/s")
        temps.append(new_temp)
        initial_temp = new_temp
    
    print(f"\nMax Temperature Reached: {max(temps):.1f}°C")
    print(f"Steady-State Temperature: {temps[-1]:.1f}°C")
    print(f"Thermal Time Constant: ~{motor_physics.thermal_capacity / motor_physics.cooling_rate:.1f}s")
    print(f"{'='*100}\n")


def mode_comparison():
    """Compare physics calculations across operating modes."""
    
    print("\n" + "="*100)
    print("MODE COMPARISON - PHYSICAL PERFORMANCE METRICS")
    print("="*100)
    
    modes = {
        'FAST': {'rpm': 9000, 'current': 45, 'coupling': [0.05, 0.20, 0.45, 0.70, 0.95]},
        'CLIMBING': {'rpm': 6000, 'current': 48, 'coupling': [0.02, 0.15, 0.40, 0.70, 1.0]},
        'CRUISE': {'rpm': 7500, 'current': 28, 'coupling': [0.08, 0.20, 0.45, 0.70, 0.90]},
        'EFFICIENCY': {'rpm': 5000, 'current': 15, 'coupling': [0.15, 0.30, 0.50, 0.70, 0.85]},
        'AIRPLANE': {'rpm': 6500, 'current': 22, 'coupling': [0.10, 0.25, 0.45, 0.70, 0.88]},
    }
    
    motor_physics = MotorPhysics()
    
    print(f"\n{'Mode':<15} {'RPM':<10} {'Current':<10} {'Output Torque':<15} {'Power (W)':<12} {'Efficiency':<12}")
    print(f"{'-'*90}")
    
    for mode_name, params in modes.items():
        rpm = params['rpm']
        current = params['current']
        omega = SpeedDynamics.angular_velocity_rad_s(rpm)
        
        # Calculate total torque from coupling fractions
        total_torque = sum(
            current * motor_physics.torque_constant * (1.0 + i * 0.2)
            for i in range(5)
        )
        
        # Power output
        power_out = EnergyCalculator.mechanical_power_output(total_torque, omega)
        
        # Power input
        power_in = EnergyCalculator.electrical_power_input(48.0, current)
        
        # Efficiency
        efficiency = (power_out / max(power_in, 1e-6)) * 100
        
        print(f"{mode_name:<15} {rpm:<10.0f} {current:<10.1f} {total_torque:<15.2f} "
              f"{power_out:<12.1f} {efficiency:<12.1f}%")
    
    print(f"{'='*100}\n")


if __name__ == '__main__':
    analyze_cascade_stages(num_stages=5, load_fraction=0.5)
    thermal_analysis()
    mode_comparison()

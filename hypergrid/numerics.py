"""Fixed-step RK4 with explicit output boundaries and finite-state checks."""
import math
from .energy import finite


def rk4_step(rhs, t, state, dt):
    finite('dt', dt, 1e-15)
    def evaluate(time, values):
        result = tuple(rhs(time, values))
        if len(result) != len(state) or not all(math.isfinite(v) for v in result):
            raise ValueError('RHS dimension mismatch or nonfinite derivative')
        return result
    k1 = evaluate(t, state)
    k2 = evaluate(t + dt/2, [y + dt*k/2 for y, k in zip(state, k1)])
    k3 = evaluate(t + dt/2, [y + dt*k/2 for y, k in zip(state, k2)])
    k4 = evaluate(t + dt, [y + dt*k for y, k in zip(state, k3)])
    out = tuple(y + dt*(a + 2*b + 2*c + d)/6 for y, a, b, c, d in zip(state, k1, k2, k3, k4))
    if not all(math.isfinite(v) for v in out):
        raise ValueError('Nonfinite state; reduce timestep or correct parameters')
    return out


def integrate(rhs, initial, duration_s, step_s):
    finite('duration_s', duration_s, 1e-15)
    finite('step_s', step_s, 1e-15)
    if duration_s / step_s > 10_000_000:
        raise ValueError('Integration budget exceeded')
    if not initial or not all(math.isfinite(v) for v in initial):
        raise ValueError('Initial state must be nonempty and finite')
    t, state = 0.0, tuple(initial)
    while t < duration_s:
        dt = min(step_s, duration_s - t)
        state = rk4_step(rhs, t, state, dt)
        t += dt
    return state


def reference_benchmarks():
    """Independent closed-form oracles; not whole-city physical validation."""
    cases = [
        ('RC_voltage_step', lambda t, y: ((12-y[0])/0.1,), (0.,), 0.5,
         12*(1-math.exp(-5)), 0.01),
        ('RL_current_step', lambda t, y: ((10-2*y[0])/0.2,), (0.,), 0.5,
         5*(1-math.exp(-5)), 0.01),
        ('linearized_swing_speed', lambda t, y: ((0.2-0.4*y[0])/2,), (0.,), 5.,
         0.5*(1-math.exp(-1)), 0.1),
        ('thermal_first_order', lambda t, y: ((100-5*(y[0]-20))/1000,), (20.,), 1000.,
         20+20*(1-math.exp(-5)), 20.)]
    results = []
    for name, rhs, initial, duration, exact, step in cases:
        values = [integrate(rhs, initial, duration, step/factor)[0] for factor in [1, 2, 4]]
        errors = [abs(value-exact) for value in values]
        # Relative to nonzero final reference, not a universal percent accuracy.
        relative = errors[-1] / abs(exact)
        results.append({'case': name, 'reference': exact, 'steps_s': [step, step/2, step/4],
                        'computed': values, 'absolute_errors': errors,
                        'finest_relative_error': relative,
                        'observed_orders': [math.log2(errors[i]/errors[i+1])
                                            if errors[i] > 0 and errors[i+1] > 0 else None for i in range(2)],
                        'passes_one_percent_reference_tolerance': relative <= 0.01})
    return results

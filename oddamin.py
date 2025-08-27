# app.py
import math
import pandas as pd
import streamlit as st

# --------------------------
# Poisson helpers
# --------------------------
def poisson_cdf(k, mu):
    if k < 0:
        return 0.0
    term = math.exp(-mu)
    s = term
    for i in range(1, k+1):
        term *= mu / i
        s += term
        if term < 1e-15:
            break
    return s

def prob_over(line_L, goals_so_far, mu_remaining):
    k = int(math.floor(line_L - goals_so_far))
    return 1.0 - poisson_cdf(k, mu_remaining)

def prob_under(line_L, goals_so_far, mu_remaining):
    k = int(math.floor(line_L - goals_so_far))
    return poisson_cdf(k, mu_remaining)

def prob_to_odd(prob):
    prob = min(max(prob, 1e-9), 1 - 1e-9)
    return 1.0 / prob

# --------------------------
# Inversión de μ
# --------------------------
def invert_mu_from_prob(target_prob, line_L, goals_so_far, is_over=True, lo=1e-9, hi=10.0, iters=70):
    a, b = lo, hi
    for _ in range(iters):
        m = 0.5 * (a + b)
        f = prob_over(line_L, goals_so_far, m) if is_over else prob_under(line_L, goals_so_far, m)
        if is_over:  # creciente
            if f > target_prob:
                b = m
            else:
                a = m
        else:       # decreciente
            if f > target_prob:
                a = m
            else:
                b = m
    return 0.5 * (a + b)

# --------------------------
# Limpieza de vig (opcional)
# --------------------------
def de_vig_two_outcomes(p1, p2):
    s = p1 + p2
    if s <= 0:
        return p1, p2
    return p1 / s, p2 / s

# --------------------------
# Proyección CORREGIDA
# --------------------------
def project_ou_odd(
    odd_over=None,
    odd_under=None,
    minute_current=21,
    minute_target=45,
    line_L=2.5,
    goals_so_far=0,
    add_minutes_total=0,
    remove_vig=True,
    future_goal_minutes=None
):
    assert odd_over or odd_under, "Debes ingresar al menos la odd del Over o del Under."

    # Probabilidades implícitas actuales
    p_over_raw  = (1.0 / odd_over) if odd_over else None
    p_under_raw = (1.0 / odd_under) if odd_under else None

    if p_over_raw is None:
        p_over, p_under = 1.0 - p_under_raw, p_under_raw
    elif p_under_raw is None:
        p_over, p_under = p_over_raw, 1.0 - p_over_raw
    else:
        p_over, p_under = p_over_raw, p_under_raw

    if remove_vig:
        p_over, p_under = de_vig_two_outcomes(p_over, p_under)

    # Invertir μ
    mu_from_over  = invert_mu_from_prob(p_over,  line_L, goals_so_far, is_over=True)
    mu_from_under = invert_mu_from_prob(p_under, line_L, goals_so_far, is_over=False)
    mu_now = 0.5 * (mu_from_over + mu_from_under)

    # Escalar μ
    horizon = 90.0 + max(0.0, add_minutes_total)
    time_left_now    = max(0.0, horizon - minute_current)
    time_left_target = max(0.0, horizon - minute_target)
    
    # CORRECCIÓN: Asegurar que no dividimos por cero
    if time_left_now <= 0:
        mu_target = 0.0
    else:
        mu_target = mu_now * (time_left_target / time_left_now)

    # Ajustar goles efectivos
    extra_goals = 0
    if future_goal_minutes:
        # CORRECCIÓN: Filtrar correctamente los minutos de goles futuros
        extra_goals = sum(1 for m in future_goal_minutes if minute_current < m <= minute_target)
    goals_effective = goals_so_far + extra_goals

    # Probs y odds con los goles efectivos
    p_over_t = prob_over(line_L, goals_effective, mu_target)
    p_under_t = 1.0 - p_over_t
    odd_over_t  = prob_to_odd(p_over_t)
    odd_under_t = prob_to_odd(p_under_t)

    # Variación %
    var_over = None
    var_under = None
    if odd_over:
        var_over = (odd_over_t - odd_over) / odd_over * 100
    if odd_under:
        var_under = (odd_under_t - odd_under) / odd_under * 100

    return {
        "p_over_now": p_over,
        "p_under_now": p_under,
        "p_over_target": p_over_t,
        "p_under_target": p_under_t,
        "odd_over_target": odd_over_t,
        "odd_under_target": odd_under_t,
        "mu_now": mu_now,
        "mu_target": mu_target,
        "horizon": horizon,
        "var_over": var_over,
        "var_under": var_under,
        "goals_effective": goals_effective,
        "extra_goals": extra_goals
    }

# --------------------------
# UI Streamlit
# --------------------------
st.title("📊 Proyector de Odds Over/Under (con goles futuros)")

col1, col2 = st.columns(2)
with col1:
    odd_over = st.number_input("Odd actual Over (L.5)", min_value=1.01, value=2.40, step=0.01)
    odd_under = st.number_input("Odd actual Under (opcional)", min_value=0.0, value=0.0, step=0.01,
                                help="Si no la tienes, déjala en 0")
    line_L = st.number_input("Línea (ej: 2.5)", value=2.5, step=1.0)
with col2:
    goals_so_far = st.number_input("Goles totales actuales", min_value=0, value=0, step=1)
    minute_current = st.slider("Minuto actual", 0, 120, 21)
    minute_target  = st.slider("Minuto objetivo", 0, 120, 45)
    add_minutes_total = st.number_input("Minutos de adición totales", min_value=0, value=0, step=1)

# --------------------------
# Nueva tabla para goles futuros
# --------------------------
st.markdown("### ⚽ Goles futuros estimados")
st.markdown("Ingresa los minutos en los que esperas que se marquen goles adicionales")

default_df = pd.DataFrame({"Minuto Gol Esperado": []})
future_goals_df = st.data_editor(
    default_df,
    num_rows="dynamic",
    use_container_width=True,
    key="future_goals_editor"
)

future_goal_minutes = []
if not future_goals_df.empty:
    # CORRECCIÓN: Manejar mejor la entrada de datos
    try:
        future_goal_minutes = [int(float(m)) for m in future_goals_df["Minuto Gol Esperado"].dropna() if str(m).replace('.', '').isdigit()]
    except:
        st.warning("Algunos valores de minutos de gol no son válidos. Usando solo los valores numéricos.")
        future_goal_minutes = [int(float(m)) for m in future_goals_df["Minuto Gol Esperado"].dropna() if str(m).replace('.', '').isdigit()]

remove_vig = st.checkbox("Quitar vig (recomendado si ingresas Over y Under)", value=True)

if st.button("Calcular proyección"):
    # Validación adicional
    if minute_target <= minute_current:
        st.error("El minuto objetivo debe ser mayor al minuto actual.")
    else:
        res = project_ou_odd(
            odd_over=odd_over if odd_over > 0 else None,
            odd_under=odd_under if odd_under > 0 else None,
            minute_current=minute_current,
            minute_target=minute_target,
            line_L=line_L,
            goals_so_far=goals_so_far,
            add_minutes_total=add_minutes_total,
            remove_vig=remove_vig,
            future_goal_minutes=future_goal_minutes
        )

        st.subheader("Resultados")
        st.write(f"⏱ Horizonte usado: {res['horizon']:.0f} min")
        st.write(f"μ ahora: {res['mu_now']:.3f} | μ objetivo: {res['mu_target']:.3f}")
        st.write(f"⚽ Goles actuales: {goals_so_far}, goles futuros asumidos: {res['extra_goals']} → total efectivo: {res['goals_effective']}")
        if future_goal_minutes:
            st.write(f"   (Minutos considerados: {sorted(future_goal_minutes)})")

        st.markdown("**Estado actual (implícito por la odd actual):**")
        st.write(f"• Prob Over ahora:  {res['p_over_now']:.3f}")
        st.write(f"• Prob Under ahora: {res['p_under_now']:.3f}")

        st.markdown("**Proyección al minuto objetivo:**")
        st.write(f"📈 Prob Over objetivo:  {res['p_over_target']:.3f}")
        st.write(f"📉 Prob Under objetivo: {res['p_under_target']:.3f}")
        st.write(f"💰 Odd Over proyectada:  {res['odd_over_target']:.2f}")
        if res['var_over'] is not None:
            st.write(f"   ↳ Variación Over: {res['var_over']:+.2f}%")
        st.write(f"💰 Odd Under proyectada: {res['odd_under_target']:.2f}")
        if res['var_under'] is not None:
            st.write(f"   ↳ Variación Under: {res['var_under']:+.2f}%")

from datetime import datetime
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ==========================================
# CONSTANTES LEGALES Y ECONOMICAS (MEXICO 2026)
# ==========================================
SMG_GENERAL_2026 = 315.04
SMG_FRONTERA_2026 = 440.87
UMA_DIARIA_2026 = 117.31

app = FastAPI(
    title="Motor de Cálculo de Liquidaciones Laborales MX (2026)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TipoZona(str, Enum):
    GENERAL = "general"
    FRONTERA = "frontera"

class MotivoSalida(str, Enum):
    RENUNCIA = "renuncia_voluntaria"
    DESPIDO_INJUSTIFICADO = "despido_injustificado"
    FIN_CONTRATO = "fin_contrato"

class CalculoRequest(BaseModel):
    salario_mensual_bruto: float = Field(..., gt=0)
    fecha_ingreso: str
    fecha_salida: str
    motivo_salida: MotivoSalida
    zona_geografica: TipoZona = TipoZona.GENERAL
    dias_vacaciones_pendientes_periodos_anteriores: int = Field(0, ge=0)
    incluir_20_dias_por_ano: bool = False

def obtener_dias_vacaciones_ley(anios_cumplidos: int) -> int:
    if anios_cumplidos < 1:
        return 12
    elif anios_cumplidos == 1:
        return 12
    elif anios_cumplidos == 2:
        return 14
    elif anios_cumplidos == 3:
        return 16
    elif anios_cumplidos == 4:
        return 18
    elif anios_cumplidos == 5:
        return 20
    elif 6 <= anios_cumplidos <= 10:
        return 22
    elif 11 <= anios_cumplidos <= 15:
        return 24
    elif 16 <= anios_cumplidos <= 20:
        return 26
    elif 21 <= anios_cumplidos <= 25:
        return 28
    else:
        return 30

@app.post("/api/v1/calcular-liquidacion")
def calcular_liquidacion(req: CalculoRequest):
    try:
        f_ingreso = datetime.strptime(req.fecha_ingreso, "%Y-%m-%d")
        f_salida = datetime.strptime(req.fecha_salida, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usar YYYY-MM-DD")

    if f_salida <= f_ingreso:
        raise HTTPException(status_code=400, detail="La fecha de salida debe ser posterior a la fecha de ingreso.")

    dias_totales = (f_salida - f_ingreso).days
    anios_completos = dias_totales // 365
    dias_proporcionales_ultimo_anio = dias_totales % 365

    inicio_anio_actual = datetime(f_salida.year, 1, 1)
    dias_anio_curso = (f_salida - inicio_anio_actual).days + 1

    salario_diario = req.salario_mensual_bruto / 30.0
    smg_aplicable = SMG_FRONTERA_2026 if req.zona_geografica == TipoZona.FRONTERA else SMG_GENERAL_2026

    if salario_diario < smg_aplicable:
        salario_diario = smg_aplicable

    dias_vac_primer_anio = obtener_dias_vacaciones_ley(anios_completos + 1)
    factor_integracion = (365 + 15 + (dias_vac_primer_anio * 0.25)) / 365.0
    sdi = salario_diario * factor_integracion

    dias_aguinaldo_prop = (15 / 365.0) * dias_anio_curso
    monto_aguinaldo = dias_aguinaldo_prop * salario_diario

    dias_vac_correspondientes = obtener_dias_vacaciones_ley(anios_completos)
    dias_vac_proporcionales = (dias_vac_correspondientes / 365.0) * dias_proporcionales_ultimo_anio
    dias_vac_totales_pagar = dias_vac_proporcionales + req.dias_vacaciones_pendientes_periodos_anteriores
    monto_vacaciones = dias_vac_totales_pagar * salario_diario
    monto_prima_vacacional = monto_vacaciones * 0.25

    subtotal_finiquito = monto_aguinaldo + monto_vacaciones + monto_prima_vacacional

    monto_indemnizacion_3_meses = 0.0
    monto_20_dias_por_ano = 0.0
    monto_prima_antiguedad = 0.0

    aplica_prima_antiguedad = (req.motivo_salida == MotivoSalida.DESPIDO_INJUSTIFICADO) or \
                              (req.motivo_salida == MotivoSalida.RENUNCIA and anios_completos >= 15)

    if aplica_prima_antiguedad:
        tope_salario_prima = min(salario_diario, 2 * smg_aplicable)
        dias_prima_antiguedad = (12 / 365.0) * dias_totales
        monto_prima_antiguedad = dias_prima_antiguedad * tope_salario_prima

    if req.motivo_salida == MotivoSalida.DESPIDO_INJUSTIFICADO:
        monto_indemnizacion_3_meses = 90 * sdi
        if req.incluir_20_dias_por_ano:
            dias_20_totales = (20 / 365.0) * dias_totales
            monto_20_dias_por_ano = dias_20_totales * sdi

    subtotal_indemnizaciones = monto_indemnizacion_3_meses + monto_20_dias_por_ano + monto_prima_antiguedad
    total_bruto = subtotal_finiquito + subtotal_indemnizaciones

    exencion_aguinaldo = min(monto_aguinaldo, 30 * UMA_DIARIA_2026)
    exencion_prima_vacacional = min(monto_prima_vacacional, 15 * UMA_DIARIA_2026)
    anios_para_exencion = max(1, anios_completos)
    exencion_indemnizaciones = min(subtotal_indemnizaciones, anios_para_exencion * (90 * UMA_DIARIA_2026))

    total_exento = exencion_aguinaldo + exencion_prima_vacacional + exencion_indemnizaciones + monto_vacaciones
    monto_gravable_estimado = max(0.0, total_bruto - total_exento)

    return {
        "resumen": {
            "dias_totales_laborados": dias_totales,
            "anios_completos": anios_completos,
            "salario_diario_base": round(salario_diario, 2),
            "salario_diario_integrado_estimado": round(sdi, 2),
            "zona": req.zona_geografica.value,
        },
        "desglose_finiquito": {
            "aguinaldo_proporcional": round(monto_aguinaldo, 2),
            "vacaciones": round(monto_vacaciones, 2),
            "prima_vacacional": round(monto_prima_vacacional, 2),
            "subtotal": round(subtotal_finiquito, 2),
        },
        "desglose_indemnizacion": {
            "tres_meses_salario": round(monto_indemnizacion_3_meses, 2),
            "prima_de_antiguedad": round(monto_prima_antiguedad, 2),
            "veinte_dias_por_ano": round(monto_20_dias_por_ano, 2),
            "subtotal": round(subtotal_indemnizaciones, 2),
        },
        "fiscal_estimado": {
            "monto_total_bruto": round(total_bruto, 2),
            "monto_exento_impuestos": round(total_exento, 2),
            "monto_sujeto_a_isr": round(monto_gravable_estimado, 2),
        },
    }
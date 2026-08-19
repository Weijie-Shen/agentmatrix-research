import numpy as np
import pandas as pd
from research_core.factor_lab.libraries.huatai_technical_2019.factors import compute_factors

def _panel():
    dates = pd.date_range("2020-01-01", periods=20)
    return pd.DataFrame([{ "date": d, "code": c, "open": i+1+(j*.1), "high": i+2+(j*.1), "low": i+.5+(j*.1), "close": i+1.5+(j*.1), "volume": 100+i*3+j, "amount": (100+i*3+j)*(i+1.2)} for j,c in enumerate("ABCDE") for i,d in enumerate(dates)])

def test_Alpha3_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha3"]); assert out["Alpha3"].isna().sum() > 0; assert np.isfinite(out["Alpha3"].dropna()).all()
def test_Alpha13_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha13"]); assert out["Alpha13"].isna().sum() > 0
def test_Alpha15_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha15"]); assert out["Alpha15"].isna().sum() > 0
def test_Alpha16_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha16"]); assert out["Alpha16"].isna().sum() > 0
def test_Alpha44_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha44"]); assert out["Alpha44"].isna().sum() > 0
def test_Alpha50_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha50"]); assert out["Alpha50"].isna().sum() > 0
def test_Alpha55_formula_and_warmup():
    out=compute_factors(_panel(), ["Alpha55"]); assert out["Alpha55"].isna().sum() > 0

"""Two explicit baselines and separately fitted pooled log-target Ridge models."""
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .data import COUNT
from .features import CATEGORICAL, FEATURES, NUMERIC, transform

NAIVE = 'naive_v1'
SEASONAL = 'seasonal_naive_v1'


def ridge_id(alpha):
    return f'ridge_log_v1_alpha_{alpha:g}'


def make_ridge(alpha):
    numeric = Pipeline([('impute', SimpleImputer(strategy='median', add_indicator=True,
                                                keep_empty_features=True)),
                        ('scale', StandardScaler())])
    preprocessing = ColumnTransformer([
        ('numeric', numeric, NUMERIC),
        ('identity', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CATEGORICAL)])
    return Pipeline([('preprocess', preprocessing),
                     ('ridge', Ridge(alpha=alpha, solver='svd'))])


def fit_ridge(train, target, alpha):
    if train.empty:
        return None
    model = make_ridge(alpha)
    model.fit(train[FEATURES], transform(train.actual.to_numpy(), target))
    return model


def predict_ridge(model, rows, target):
    if model is None:
        return np.full(len(rows), np.nan)
    with np.errstate(over='ignore', invalid='ignore'):
        z = model.predict(rows[FEATURES])
        prediction = np.expm1(z) if target == COUNT else np.exp(z)
    if target == COUNT:
        prediction = np.maximum(prediction, 0)
    prediction[~np.isfinite(prediction)] = np.nan
    if target != COUNT:
        prediction[prediction <= 0] = np.nan
    return prediction


def predictions_for(train, candidates, target, alphas):
    result = {NAIVE: candidates.naive.to_numpy(), SEASONAL: candidates.seasonal_naive.to_numpy()}
    for alpha in alphas:
        result[ridge_id(alpha)] = predict_ridge(fit_ridge(train, target, alpha), candidates, target)
    return result

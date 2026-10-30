"""Methods the fuzzy classifier is compared against: crisp rules and k-means."""
import numpy as np
from sklearn.cluster import KMeans

FEATURES = ['log_price_change', 'log_volume_change', 'volatility']


def crisp_labels(df, scales):
    """Price-only thresholds at the fuzzy crossover point, (a + b) / 2."""
    threshold = sum(scales['price']) / 2
    x = df.log_price_change
    return np.select([x > threshold, x < -threshold], ['Rising', 'Declining'], 'Stable')


def kmeans_labels(df, seed, n_init=10):
    """Three k-means clusters on standardised features, named by mean price change.

    Rows with a missing feature get no label (None).
    """
    complete = df[FEATURES].notna().all(axis=1).to_numpy()
    x = df.loc[complete, FEATURES].to_numpy()
    x = (x - x.mean(axis=0)) / x.std(axis=0)
    model = KMeans(n_clusters=3, n_init=n_init, random_state=seed).fit(x)
    order = np.argsort(model.cluster_centers_[:, 0])  # lowest price change first
    names = np.empty(3, dtype=object)
    names[order] = ['Declining', 'Stable', 'Rising']
    labels = np.full(len(df), None, dtype=object)
    labels[complete] = names[model.labels_]
    return labels

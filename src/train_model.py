import warnings

warnings.filterwarnings(action="ignore")

from functools import partial
from typing import Callable

import hydra
import joblib
import mlflow
import numpy as np
import pandas as pd
from hydra.utils import to_absolute_path as abspath
from hyperopt import STATUS_OK, Trials, fmin, hp, tpe
from omegaconf import DictConfig
from sklearn.metrics import accuracy_score, f1_score
from xgboost import XGBClassifier

from helper import BaseLogger

logger = BaseLogger()


def load_data(path: DictConfig):
    X_train = pd.read_csv(abspath(path.X_train.path))
    X_test = pd.read_csv(abspath(path.X_test.path))
    y_train = pd.read_csv(abspath(path.y_train.path))
    y_test = pd.read_csv(abspath(path.y_test.path))
    return X_train, X_test, y_train, y_test


def get_objective(
    X_train: pd.DataFrame,
    y_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_test: pd.DataFrame,
    config: DictConfig,
    space: dict,
):

    model = XGBClassifier(
        use_label_encoder=config.model.use_label_encoder,
        objective=config.model.objective,
        n_estimators=space["n_estimators"],
        max_depth=int(space["max_depth"]),
        gamma=space["gamma"],
        reg_alpha=int(space["reg_alpha"]),
        min_child_weight=int(space["min_child_weight"]),
        colsample_bytree=int(space["colsample_bytree"]),
    )

    evaluation = [(X_train, y_train), (X_test, y_test)]

    model.fit(
        X_train,
        y_train,
        eval_set=evaluation,
        eval_metric=config.model.eval_metric,
        early_stopping_rounds=config.model.early_stopping_rounds,
    )
    prediction = model.predict(X_test)
    print(prediction)
    accuracy = accuracy_score(y_test, prediction)
    print("SCORE:", accuracy)
    return {"loss": -accuracy, "status": STATUS_OK, "model": model}


def optimize(objective: Callable, space: dict):
    trials = Trials()
    best_hyperparams = fmin(
        fn=objective,
        space=space,
        algo=tpe.suggest,
        max_evals=100,
        trials=trials,
    )
    print("The best hyperparameters are : ", "\n")
    print(best_hyperparams)
    best_model = trials.results[
        np.argmin([r["loss"] for r in trials.results])
    ]["model"]
    return best_model


def predict(model: XGBClassifier, X_test: pd.DataFrame):
    return model.predict(X_test)


def log_params(model: XGBClassifier, features: list):
    logger.log_params({"model_class": type(model).__name__})
    model_params = model.get_params()

    for arg, value in model_params.items():
        logger.log_params({arg: value})

    logger.log_params({"features": features})


def log_metrics(**metrics: dict):
    logger.log_metrics(metrics)


@hydra.main(config_path="../config", config_name="main")
def train(config: DictConfig):
    """Function to train the model"""

    mlflow.set_tracking_uri(config.mlflow_tracking_ui)

    with mlflow.start_run():

        X_train, X_test, y_train, y_test = load_data(config.processed)

        # Define space
        space = {
            "max_depth": hp.quniform("max_depth", **config.model.max_depth),
            "gamma": hp.uniform("gamma", **config.model.gamma),
            "reg_alpha": hp.quniform("reg_alpha", **config.model.reg_alpha),
            "reg_lambda": hp.uniform("reg_lambda", **config.model.reg_lambda),
            "colsample_bytree": hp.uniform(
                "colsample_bytree", **config.model.colsample_bytree
            ),
            "min_child_weight": hp.quniform(
                "min_child_weight", **config.model.min_child_weight
            ),
            "n_estimators": config.model.n_estimators,
            "seed": config.model.seed,
        }
        objective = partial(
            get_objective, X_train, y_train, X_test, y_test, config
        )

        # Find best model
        best_model = optimize(objective, space)

        # Predict
        prediction = predict(best_model, X_test)

        # Get metrics
        f1 = f1_score(y_test, prediction)
        print(f"F1 Score of this model is {f1}.")

        accuracy = accuracy_score(y_test, prediction)
        print(f"Accuracy Score of this model is {accuracy}.")

        # Log parameters and metrics
        log_params(best_model, config.process.features)
        log_metrics(f1_score=f1, accuracy_score=accuracy)

        # Save model
        joblib.dump(best_model, abspath(config.model.path))


if __name__ == "__main__":
    train()

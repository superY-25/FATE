import json
import numpy as np

from federatedml.protobuf.generated.lr_model_param_pb2 import LRModelParam
from federatedml.protobuf.generated.lr_model_meta_pb2 import LRModelMeta
from sklearn.linear_model import LogisticRegression
from sklearn2pmml.pipeline import PMMLPipeline
from google.protobuf import json_format


def _get_coef(param_obj):
    coefficient = np.empty((1, len(param_obj.header)))
    weight_dict = dict(param_obj.weight)
    for index in range(len(param_obj.header)):
        coefficient[0][index] = weight_dict[param_obj.header[index]]
    return coefficient


def _merge_single_model_coef(guest_pb_param, host_pb_param, include_guest_coef):
    host_coef = _get_coef(host_pb_param)
    if include_guest_coef:
        guest_coef = _get_coef(guest_pb_param)
        coef = np.concatenate((guest_coef, host_coef), axis=1)
        return coef
    return host_coef


def merge_lr(guest_param: dict, guest_meta: dict, host_params: list, host_metas: list, output_format: str,
             include_guest_coef=False):
    # check for multi-host
    if len(host_params) > 1 or len(host_metas) > 1:
        raise ValueError(f"Cannot merge Hetero LR models from multiple hosts. Please check input")
    host_param, host_meta = host_params[0], host_metas[0]
    pb_meta = json_format.Parse(json.dumps(guest_meta), LRModelMeta())
    # set up model
    sk_lr_model = LogisticRegression(penalty=pb_meta.penalty.lower(),
                                     tol=pb_meta.tol,
                                     fit_intercept=pb_meta.fit_intercept,
                                     max_iter=pb_meta.max_iter,
                                     multi_class="ovr",
                                     solver="saga")
    if pb_meta.need_one_vs_rest:
        guest_pb_param_c = json_format.Parse(json.dumps(guest_param), LRModelParam())
        host_pb_param_c = json_format.Parse(json.dumps(host_param), LRModelParam())
        sk_lr_model.classes_ = np.array(guest_pb_param_c.one_vs_rest_result.one_vs_rest_classes)

        guest_pb_models = guest_pb_param_c.one_vs_rest_result.completed_models
        host_pb_models = host_pb_param_c.one_vs_rest_result.completed_models
        coef_list, intercept_list, iters_list = [], [], []
        for guest_single_pb_param, host_single_pb_param in zip(guest_pb_models, host_pb_models):
            coef = _merge_single_model_coef(guest_single_pb_param, host_single_pb_param, include_guest_coef)
            coef_list.append(coef)
            intercept_list.append(guest_single_pb_param.intercept)
            iters_list.append(guest_single_pb_param.iters)
        sk_lr_model.coef_ = np.concatenate(coef_list, axis=0)
        sk_lr_model.intercept_ = np.array(intercept_list)
        sk_lr_model.n_iter_ = np.array(iters_list)

    else:
        guest_pb_param = json_format.Parse(json.dumps(guest_param), LRModelParam())
        host_pb_param = json_format.Parse(json.dumps(host_param), LRModelParam())
        sk_lr_model.classes_ = np.array([0, 1])
        sk_lr_model.n_iter_ = np.array([guest_pb_param.iters])

        coef = _merge_single_model_coef(guest_pb_param, host_pb_param, include_guest_coef)
        sk_lr_model.coef_ = coef
        sk_lr_model.intercept_ = np.array([guest_pb_param.intercept])

    if output_format in ['sklearn', 'scikit-learn']:
        return sk_lr_model
    elif output_format in ['pmml']:
        pipeline = PMMLPipeline([("classifier", sk_lr_model)])
        return pipeline

    else:
        raise ValueError('unknown output type {}'.format(output_format))

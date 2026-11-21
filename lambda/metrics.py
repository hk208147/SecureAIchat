import json
import time
import config


def emit_request_metrics(function_name: str, input_tokens: int, output_tokens: int) -> None:
    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": config.EMF_NAMESPACE,
                    "Dimensions": [["FunctionName"]],
                    "Metrics": [
                        {"Name": "InputTokens", "Unit": "Count"},
                        {"Name": "OutputTokens", "Unit": "Count"},
                    ],
                }
            ],
        },
        "FunctionName": function_name,
        "InputTokens": input_tokens,
        "OutputTokens": output_tokens,
    }
    print(json.dumps(emf))

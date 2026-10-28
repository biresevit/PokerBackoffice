import azure.functions as func

from backoffice.app import Request, handle

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="{*path}", methods=["GET", "POST", "PUT", "DELETE"])
def backoffice_api(req: func.HttpRequest) -> func.HttpResponse:
    result = handle(Request(req.method, "/api/" + req.route_params.get("path", ""),
                            dict(req.headers), dict(req.params), req.get_body()))
    return func.HttpResponse(result.body, status_code=result.status, headers=result.headers)

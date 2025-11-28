规则描述：

功能调用方式

所有功能或方法必须通过导入模块进行调用。

不要生成 Flask、FastAPI 或任何 web 框架的路由装饰器、@app.route、@router.get 等。

例如，功能应写作：

from my_project.services import gnn_data_conversion_service

debug_info = gnn_data_conversion_service.debug_neo4j_processor()
print(debug_info)


不要写作：

@app.route('/api/debug/neo4j-methods', methods=['GET'])
def debug_neo4j_methods():
    ...


输出方式

如果需要返回结果，直接返回对象或打印日志，而不是构造 HTTP Response。

API 层或路由层代码应由实际项目框架单独编写。

日志与异常

可以使用标准 Python logging 模块进行日志记录。

异常处理使用 try-except，但不返回 HTTP 状态码。
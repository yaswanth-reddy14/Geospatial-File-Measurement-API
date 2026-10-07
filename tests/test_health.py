def test_health_and_docs(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/").json()["docs"] == "/docs"
    assert "swagger-ui" in client.get("/docs").text
    assert "redoc" in client.get("/redoc").text
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/files/"]["post"]["requestBody"]["content"]["multipart/form-data"]
    assert schema["components"]["schemas"]["MeasurementsResponse"]["properties"]["measurement_crs"]

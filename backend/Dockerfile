FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /build
COPY pom.xml .
COPY settings-mirror.xml .
RUN mvn -q -s settings-mirror.xml -Dmaven.wagon.http.retryHandler.count=5 -Dmaven.wagon.httpconnectionManager.ttlSeconds=120 dependency:go-offline || true
COPY src ./src
RUN mvn -q -s settings-mirror.xml -Dmaven.wagon.http.retryHandler.count=5 -Dmaven.wagon.http.retryHandler.requestSentEnabled=true -Dmaven.wagon.httpconnectionManager.ttlSeconds=120 package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=builder /build/target/robot-cloud-backend-0.1.0-SNAPSHOT.jar app.jar
ENV JAVA_OPTS="-Xms256m -Xmx512m"
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
FROM maven:3.9.9-eclipse-temurin-21 AS build

WORKDIR /app

COPY backend-spring/pom.xml /app/backend-spring/pom.xml
COPY backend-spring/src /app/backend-spring/src

RUN mvn -f /app/backend-spring/pom.xml -DskipTests package

FROM eclipse-temurin:21-jre

WORKDIR /app

COPY --from=build /app/backend-spring/target/plant-backend-spring-0.1.0.jar /app/app.jar
COPY plantbackend /app/plantbackend
RUN mkdir -p \
    /app/plantbackend/models \
    /app/plantbackend/annotation_datasets \
    /app/plantbackend/training_runs \
    /app/plantbackend/runtime

EXPOSE 7800

ENTRYPOINT ["java", "-jar", "/app/app.jar"]

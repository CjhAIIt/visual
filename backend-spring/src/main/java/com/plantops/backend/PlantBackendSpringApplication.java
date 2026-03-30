package com.plantops.backend;

import com.plantops.backend.config.LegacyBackendProperties;
import com.plantops.backend.config.PlantStorageProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties({LegacyBackendProperties.class, PlantStorageProperties.class})
public class PlantBackendSpringApplication {

    public static void main(String[] args) {
        SpringApplication.run(PlantBackendSpringApplication.class, args);
    }
}
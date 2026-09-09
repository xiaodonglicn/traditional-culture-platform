package com.culture;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class TraditionalCultureApplication {
    public static void main(String[] args) {
        SpringApplication.run(TraditionalCultureApplication.class, args);
        System.out.println("🎋 传统文化智慧平台启动成功！");
        System.out.println("📍 访问地址: http://localhost:8080/api");
    }
}
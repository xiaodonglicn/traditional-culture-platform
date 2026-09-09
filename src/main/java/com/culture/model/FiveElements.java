package com.culture.model;

import lombok.Data;

import java.util.List;

@Data
public class FiveElements {
    private String element;     // 金、木、水、火、土
    private String description; // 属性描述
    private String direction;   // 方位: 西、东、北、南、中
    private String season;      // 季节
    private String color;       // 颜色
    private String generates;   // 相生: 木生火、火生土...
    private String restricts;   // 相克: 木克土、土克水...
    private List<String> characteristics; // 性格特征
    private List<String> professions;     // 适合职业
}
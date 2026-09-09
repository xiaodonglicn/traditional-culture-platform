package com.culture.model;

import lombok.Data;

@Data
public class DaoismQuote {
    private String id;
    private String source;      // 出处，如《道德经》
    private String chapter;     // 章节
    private String original;    // 原文
    private String translation; // 白话译文
    private String interpretation; // 解读
    private String category;    // 分类: 道、德、无为、自然等
}
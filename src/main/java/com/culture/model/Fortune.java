package com.culture.model;

import lombok.Data;
import java.util.List;

@Data
public class Fortune {
    private String date;
    private String zodiac;      // 生肖
    private String luckLevel;   // 运势等级: 上上签、上签、中签、下签
    private String luckScore;   // 运势分数 1-100
    private String summary;     // 总运势
    private String career;      // 事业
    private String love;        // 感情
    private String wealth;      // 财运
    private List<String> luckyColors;  // 幸运色
    private List<Integer> luckyNumbers; // 幸运数字
    private String advice;      // 建议
}
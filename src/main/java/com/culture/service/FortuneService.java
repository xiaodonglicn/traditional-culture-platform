package com.culture.service;

import com.culture.model.Fortune;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import java.io.InputStream;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

@Slf4j
@Service
public class FortuneService {
    
    private final ResourceLoader resourceLoader;
    private List<Fortune> fortuneTemplates;
    
    @Value("${culture.data-path}")
    private String dataPath;
    
    private static final String[] ZODIACS = {
        "鼠", "牛", "虎", "兔", "龙", "蛇", 
        "马", "羊", "猴", "鸡", "狗", "猪"
    };
    
    private static final String[] LUCK_LEVELS = {"上上签", "上签", "中签", "下签"};
    private static final String[] COLORS = {"红色", "金色", "蓝色", "绿色", "紫色", "白色", "黑色", "黄色"};
    
    public FortuneService(ResourceLoader resourceLoader) {
        this.resourceLoader = resourceLoader;
    }
    
    @PostConstruct
    public void init() {
        loadFortuneTemplates();
    }
    
    private void loadFortuneTemplates() {
        try {
            Resource resource = resourceLoader.getResource("classpath:/data/fortunes.json");
            if (resource.exists()) {
                try (InputStream is = resource.getInputStream()) {
                    ObjectMapper mapper = new ObjectMapper();
                    fortuneTemplates = mapper.readValue(is, 
                        mapper.getTypeFactory().constructCollectionType(List.class, Fortune.class));
                    log.info("加载运势模板成功，共 {} 条", fortuneTemplates.size());
                }
            } else {
                log.warn("运势模板文件不存在，使用默认数据");
                fortuneTemplates = createDefaultFortuneTemplates();
            }
        } catch (Exception e) {
            log.error("加载运势模板失败", e);
            fortuneTemplates = createDefaultFortuneTemplates();
        }
    }
    
    private List<Fortune> createDefaultFortuneTemplates() {
        List<Fortune> templates = new ArrayList<>();
        
        Fortune f1 = new Fortune();
        f1.setLuckLevel("上上签");
        f1.setLuckScore("95");
        f1.setSummary("天时地利人和，万事皆顺，大吉大利");
        f1.setCareer("事业如日中天，升迁有望");
        f1.setLove("桃花运旺盛，情投意合");
        f1.setWealth("财源广进，投资获利");
        f1.setLuckyColors(Arrays.asList("红色", "金色"));
        f1.setLuckyNumbers(Arrays.asList(6, 8, 9));
        f1.setAdvice("保持谦逊，继续努力");
        templates.add(f1);
        
        Fortune f2 = new Fortune();
        f2.setLuckLevel("上签");
        f2.setLuckScore("80");
        f2.setSummary("诸事顺利，但需防小人是非");
        f2.setCareer("工作稳步前进，注意人际关系");
        f2.setLove("感情稳定，细水长流");
        f2.setWealth("财运平稳，宜守不宜攻");
        f2.setLuckyColors(Arrays.asList("蓝色", "白色"));
        f2.setLuckyNumbers(Arrays.asList(3, 7));
        f2.setAdvice("谨言慎行，明哲保身");
        templates.add(f2);
        
        Fortune f3 = new Fortune();
        f3.setLuckLevel("中签");
        f3.setLuckScore("65");
        f3.setSummary("平淡如水，顺势而为");
        f3.setCareer("按部就班，无大起大落");
        f3.setLove("平平淡淡，珍惜眼前人");
        f3.setWealth("收支平衡，避免大额投资");
        f3.setLuckyColors(Arrays.asList("绿色", "紫色"));
        f3.setLuckyNumbers(Arrays.asList(2, 5));
        f3.setAdvice("静心修炼，等待时机");
        templates.add(f3);
        
        Fortune f4 = new Fortune();
        f4.setLuckLevel("下签");
        f4.setLuckScore("45");
        f4.setSummary("运势低迷，需韬光养晦");
        f4.setCareer("工作受阻，宜求稳避锋芒");
        f4.setLove("感情波折，需多沟通包容");
        f4.setWealth("财运不佳，谨慎理财");
        f4.setLuckyColors(Arrays.asList("黄色", "棕色"));
        f4.setLuckyNumbers(Arrays.asList(1, 4));
        f4.setAdvice("修身养性，积德行善");
        templates.add(f4);
        
        return templates;
    }
    
    /**
     * 获取今日运势
     */
    public Fortune getDailyFortune(String zodiac) {
        // 验证生肖
        boolean validZodiac = false;
        for (String z : ZODIACS) {
            if (z.equals(zodiac)) {
                validZodiac = true;
                break;
            }
        }
        if (!validZodiac) {
            zodiac = ZODIACS[ThreadLocalRandom.current().nextInt(ZODIACS.length)];
        }
        
        // 从模板中随机选择一个
        Fortune template = fortuneTemplates.get(
            ThreadLocalRandom.current().nextInt(fortuneTemplates.size())
        );
        
        // 构建今日运势
        Fortune fortune = new Fortune();
        fortune.setDate(LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy年MM月dd日")));
        fortune.setZodiac(zodiac);
        fortune.setLuckLevel(template.getLuckLevel());
        fortune.setLuckScore(template.getLuckScore());
        fortune.setSummary(template.getSummary());
        fortune.setCareer(template.getCareer());
        fortune.setLove(template.getLove());
        fortune.setWealth(template.getWealth());
        
        // 随机选择幸运色
        List<String> colors = new ArrayList<>();
        int colorCount = ThreadLocalRandom.current().nextInt(2, 4);
        for (int i = 0; i < colorCount; i++) {
            String color = COLORS[ThreadLocalRandom.current().nextInt(COLORS.length)];
            if (!colors.contains(color)) {
                colors.add(color);
            }
        }
        fortune.setLuckyColors(colors);
        
        // 随机幸运数字
        List<Integer> numbers = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            int num = ThreadLocalRandom.current().nextInt(1, 10);
            if (!numbers.contains(num)) {
                numbers.add(num);
            }
        }
        fortune.setLuckyNumbers(numbers);
        fortune.setAdvice(template.getAdvice());
        
        return fortune;
    }
    
    /**
     * 获取所有生肖列表
     */
    public List<String> getZodiacs() {
        return Arrays.asList(ZODIACS);
    }
}
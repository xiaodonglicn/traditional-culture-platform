package com.culture.service;

import com.culture.model.FiveElements;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import java.io.InputStream;
import java.util.*;

@Slf4j
@Service
public class FiveElementsService {
    
    private final ResourceLoader resourceLoader;
    private List<FiveElements> elements;
    private Map<String, FiveElements> elementMap;
    
    @Value("${culture.data-path}")
    private String dataPath;
    
    private static final String[] ELEMENTS = {"金", "木", "水", "火", "土"};
    
    public FiveElementsService(ResourceLoader resourceLoader) {
        this.resourceLoader = resourceLoader;
        this.elementMap = new HashMap<>();
    }
    
    @PostConstruct
    public void init() {
        loadElements();
        buildElementMap();
    }
    
    private void loadElements() {
        try {
            Resource resource = resourceLoader.getResource("classpath:/data/five-elements.json");
            if (resource.exists()) {
                try (InputStream is = resource.getInputStream()) {
                    ObjectMapper mapper = new ObjectMapper();
                    elements = mapper.readValue(is, 
                        mapper.getTypeFactory().constructCollectionType(List.class, FiveElements.class));
                    log.info("加载五行数据成功，共 {} 个", elements.size());
                }
            } else {
                log.warn("五行数据文件不存在，使用默认数据");
                elements = createDefaultElements();
            }
        } catch (Exception e) {
            log.error("加载五行数据失败", e);
            elements = createDefaultElements();
        }
    }
    
    private List<FiveElements> createDefaultElements() {
        List<FiveElements> list = new ArrayList<>();
        
        FiveElements e1 = new FiveElements();
        e1.setElement("金");
        e1.setDescription("金属质地，坚硬刚强，具有变革与决断之性");
        e1.setDirection("西");
        e1.setSeason("秋");
        e1.setColor("白色");
        e1.setGenerates("金生水");
        e1.setRestricts("金克木");
        e1.setCharacteristics(Arrays.asList("刚毅果断", "重义守信", "爱憎分明", "有领导力"));
        e1.setProfessions(Arrays.asList("军警", "法官", "医生", "金融从业者"));
        list.add(e1);
        
        FiveElements e2 = new FiveElements();
        e2.setElement("木");
        e2.setDescription("树木生长，生机勃勃，具有生长与仁爱之性");
        e2.setDirection("东");
        e2.setSeason("春");
        e2.setColor("青色");
        e2.setGenerates("木生火");
        e2.setRestricts("木克土");
        e2.setCharacteristics(Arrays.asList("仁慈温和", "有同情心", "善于沟通", "有创造力"));
        e2.setProfessions(Arrays.asList("教师", "艺术家", "设计师", "心理咨询师"));
        list.add(e2);
        
        FiveElements e3 = new FiveElements();
        e3.setElement("水");
        e3.setDescription("流动不息，善于变化，具有智慧与灵活之性");
        e3.setDirection("北");
        e3.setSeason("冬");
        e3.setColor("黑色");
        e3.setGenerates("水生木");
        e3.setRestricts("水克火");
        e3.setCharacteristics(Arrays.asList("聪明智慧", "善于变通", "深谋远虑", "有洞察力"));
        e3.setProfessions(Arrays.asList("科学家", "策略师", "外交官", "网络工程师"));
        list.add(e3);
        
        FiveElements e4 = new FiveElements();
        e4.setElement("火");
        e4.setDescription("炽热向上，光明温暖，具有热烈与礼仪之性");
        e4.setDirection("南");
        e4.setSeason("夏");
        e4.setColor("赤色");
        e4.setGenerates("火生土");
        e4.setRestricts("火克金");
        e4.setCharacteristics(Arrays.asList("热情开朗", "重礼守规", "有感染力", "有远见"));
        e4.setProfessions(Arrays.asList("领导人", "表演艺术家", "公关", "教育工作者"));
        list.add(e4);
        
        FiveElements e5 = new FiveElements();
        e5.setElement("土");
        e5.setDescription("厚德载物，包容万有，具有承载与诚信之性");
        e5.setDirection("中");
        e5.setSeason("长夏");
        e5.setColor("黄色");
        e5.setGenerates("土生金");
        e5.setRestricts("土克水");
        e5.setCharacteristics(Arrays.asList("稳重诚实", "脚踏实地", "有包容心", "善于协调"));
        e5.setProfessions(Arrays.asList("管理者", "农民", "建筑师", "人力资源"));
        list.add(e5);
        
        return list;
    }
    
    private void buildElementMap() {
        for (FiveElements element : elements) {
            elementMap.put(element.getElement(), element);
        }
    }
    
    /**
     * 获取所有五行
     */
    public List<FiveElements> getAllElements() {
        return elements;
    }
    
    /**
     * 根据名称获取五行
     */
    public FiveElements getElement(String name) {
        return elementMap.get(name);
    }
    
    /**
     * 获取相生关系
     */
    public String getGeneratesRelationship(String element) {
        FiveElements e = elementMap.get(element);
        return e != null ? e.getGenerates() : null;
    }
    
    /**
     * 获取相克关系
     */
    public String getRestrictsRelationship(String element) {
        FiveElements e = elementMap.get(element);
        return e != null ? e.getRestricts() : null;
    }
    
    /**
     * 判断两个元素是否相生
     */
    public boolean isGenerates(String from, String to) {
        FiveElements e = elementMap.get(from);
        if (e == null) return false;
        return e.getGenerates().endsWith(to);
    }
    
    /**
     * 判断两个元素是否相克
     */
    public boolean isRestricts(String from, String to) {
        FiveElements e = elementMap.get(from);
        if (e == null) return false;
        return e.getRestricts().endsWith(to);
    }
}
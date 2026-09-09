package com.culture.service;

import com.culture.model.DaoismQuote;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Slf4j
@Service
public class DaoismService {
    
    private final ResourceLoader resourceLoader;
    private List<DaoismQuote> quotes;
    
    @Value("${culture.data-path}")
    private String dataPath;
    
    private static final String[] CATEGORIES = {"道", "德", "无为", "自然", "柔", "静", "不争"};
    
    public DaoismService(ResourceLoader resourceLoader) {
        this.resourceLoader = resourceLoader;
    }
    
    @PostConstruct
    public void init() {
        loadQuotes();
    }
    
    private void loadQuotes() {
        try {
            Resource resource = resourceLoader.getResource("classpath:/data/daoism.json");
            if (resource.exists()) {
                try (InputStream is = resource.getInputStream()) {
                    ObjectMapper mapper = new ObjectMapper();
                    quotes = mapper.readValue(is, 
                        mapper.getTypeFactory().constructCollectionType(List.class, DaoismQuote.class));
                    log.info("加载道家名言成功，共 {} 条", quotes.size());
                }
            } else {
                log.warn("道家名言文件不存在，使用默认数据");
                quotes = createDefaultQuotes();
            }
        } catch (Exception e) {
            log.error("加载道家名言失败", e);
            quotes = createDefaultQuotes();
        }
    }
    
    private List<DaoismQuote> createDefaultQuotes() {
        List<DaoismQuote> list = new ArrayList<>();
        
        // 道德经
        DaoismQuote q1 = new DaoismQuote();
        q1.setId("1");
        q1.setSource("《道德经》");
        q1.setChapter("第一章");
        q1.setOriginal("道可道，非常道；名可名，非常名。无名，天地之始；有名，万物之母。");
        q1.setTranslation("可以用语言表达的道，就不是永恒的道；可以用名称称呼的名，就不是永恒的名。无名是天地的始源，有名是万物的根本。");
        q1.setInterpretation("道的本质是不可言说的，任何试图用语言来定义道的做法都是有限的。我们应该超越语言的局限，直接体验道的奥妙。");
        q1.setCategory("道");
        list.add(q1);
        
        DaoismQuote q2 = new DaoismQuote();
        q2.setId("2");
        q2.setSource("《道德经》");
        q2.setChapter("第八章");
        q2.setOriginal("上善若水。水善利万物而不争，处众人之所恶，故几于道。");
        q2.setTranslation("最高的善就像水一样。水善于滋润万物而不与万物相争，停留在众人都不喜欢的地方，所以最接近道。");
        q2.setInterpretation("水具有柔软、谦卑、包容的特性，这正是道的体现。我们应当学习水的品质，以柔克刚，不与世争。");
        q2.setCategory("德");
        list.add(q2);
        
        DaoismQuote q3 = new DaoismQuote();
        q3.setId("3");
        q3.setSource("《道德经》");
        q3.setChapter("第二十五章");
        q3.setOriginal("人法地，地法天，天法道，道法自然。");
        q3.setTranslation("人取法地，地取法天，天取法道，道取法自然。");
        q3.setInterpretation("万事万物都有其遵循的法则，而这个最终的法则是自然。我们应该顺应自然规律，不要强求。");
        q3.setCategory("自然");
        list.add(q3);
        
        DaoismQuote q4 = new DaoismQuote();
        q4.setId("4");
        q4.setSource("《道德经》");
        q4.setChapter("第六十四章");
        q4.setOriginal("合抱之木，生于毫末；九层之台，起于累土；千里之行，始于足下。");
        q4.setTranslation("合抱的大树，生于细小的幼苗；九层的高台，起于一筐筐泥土；千里的远行，始于脚下的第一步。");
        q4.setInterpretation("所有伟大的成就都开始于微小的一步。我们应该注重积累，脚踏实地地前行。");
        q4.setCategory("无为");
        list.add(q4);
        
        DaoismQuote q5 = new DaoismQuote();
        q5.setId("5");
        q5.setSource("《庄子》");
        q5.setChapter("逍遥游");
        q5.setOriginal("北冥有鱼，其名为鲲。鲲之大，不知其几千里也。化而为鸟，其名为鹏。");
        q5.setTranslation("北海有一条鱼，名字叫鲲。鲲的大，不知道有几千里。变化成鸟，名字叫鹏。");
        q5.setInterpretation("庄子通过鲲鹏的寓言告诉我们，要有超越世俗的视野和追求自由的勇气。生命可以超越形体的限制，达到精神的自由。");
        q5.setCategory("自然");
        list.add(q5);
        
        DaoismQuote q6 = new DaoismQuote();
        q6.setId("6");
        q6.setSource("《道德经》");
        q6.setChapter("第三十六章");
        q6.setOriginal("柔弱胜刚强。");
        q6.setTranslation("柔弱可以战胜刚强。");
        q6.setInterpretation("看似柔弱的事物，往往蕴含着强大的生命力。以柔克刚，是道家的重要智慧。");
        q6.setCategory("柔");
        list.add(q6);
        
        return list;
    }
    
    /**
     * 获取所有名言
     */
    public List<DaoismQuote> getAllQuotes() {
        return quotes;
    }
    
    /**
     * 获取随机名言
     */
    public DaoismQuote getRandomQuote() {
        Random random = new Random();
        return quotes.get(random.nextInt(quotes.size()));
    }
    
    /**
     * 按分类获取名言
     */
    public List<DaoismQuote> getQuotesByCategory(String category) {
        List<DaoismQuote> result = new ArrayList<>();
        for (DaoismQuote quote : quotes) {
            if (category.equals(quote.getCategory())) {
                result.add(quote);
            }
        }
        return result;
    }
    
    /**
     * 获取所有分类
     */
    public List<String> getCategories() {
        List<String> categories = new ArrayList<>();
        for (DaoismQuote quote : quotes) {
            if (!categories.contains(quote.getCategory())) {
                categories.add(quote.getCategory());
            }
        }
        return categories;
    }
}
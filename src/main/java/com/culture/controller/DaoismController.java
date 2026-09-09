package com.culture.controller;

import com.culture.model.DaoismQuote;
import com.culture.service.DaoismService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/daoism")
@CrossOrigin(origins = "*")
public class DaoismController {
    
    @Autowired
    private DaoismService daoismService;
    
    /**
     * 获取所有道家名言
     */
    @GetMapping("/quotes")
    public Map<String, Object> getAllQuotes() {
        Map<String, Object> response = new HashMap<>();
        List<DaoismQuote> quotes = daoismService.getAllQuotes();
        response.put("code", 200);
        response.put("data", quotes);
        response.put("total", quotes.size());
        return response;
    }
    
    /**
     * 获取随机名言
     */
    @GetMapping("/random")
    public Map<String, Object> getRandomQuote() {
        Map<String, Object> response = new HashMap<>();
        DaoismQuote quote = daoismService.getRandomQuote();
        response.put("code", 200);
        response.put("data", quote);
        return response;
    }
    
    /**
     * 按分类获取名言
     */
    @GetMapping("/category/{category}")
    public Map<String, Object> getQuotesByCategory(@PathVariable String category) {
        Map<String, Object> response = new HashMap<>();
        List<DaoismQuote> quotes = daoismService.getQuotesByCategory(category);
        response.put("code", 200);
        response.put("data", quotes);
        response.put("total", quotes.size());
        return response;
    }
    
    /**
     * 获取所有分类
     */
    @GetMapping("/categories")
    public Map<String, Object> getCategories() {
        Map<String, Object> response = new HashMap<>();
        List<String> categories = daoismService.getCategories();
        response.put("code", 200);
        response.put("data", categories);
        return response;
    }
}
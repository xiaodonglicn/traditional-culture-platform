package com.culture.controller;

import com.culture.model.FiveElements;
import com.culture.service.FiveElementsService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/elements")
@CrossOrigin(origins = "*")
public class FiveElementsController {
    
    @Autowired
    private FiveElementsService fiveElementsService;
    
    /**
     * 获取所有五行
     */
    @GetMapping("/all")
    public Map<String, Object> getAllElements() {
        Map<String, Object> response = new HashMap<>();
        List<FiveElements> elements = fiveElementsService.getAllElements();
        response.put("code", 200);
        response.put("data", elements);
        return response;
    }
    
    /**
     * 获取单个五行详情
     */
    @GetMapping("/{name}")
    public Map<String, Object> getElement(@PathVariable String name) {
        Map<String, Object> response = new HashMap<>();
        FiveElements element = fiveElementsService.getElement(name);
        if (element != null) {
            response.put("code", 200);
            response.put("data", element);
        } else {
            response.put("code", 404);
            response.put("message", "未找到该五行");
        }
        return response;
    }
    
    /**
     * 获取相生相克关系
     */
    @GetMapping("/relationship")
    public Map<String, Object> getRelationship(@RequestParam String element) {
        Map<String, Object> response = new HashMap<>();
        FiveElements e = fiveElementsService.getElement(element);
        if (e != null) {
            response.put("code", 200);
            response.put("generates", e.getGenerates());
            response.put("restricts", e.getRestricts());
        } else {
            response.put("code", 404);
            response.put("message", "未找到该五行");
        }
        return response;
    }
    
    /**
     * 判断相生关系
     */
    @GetMapping("/check/generates")
    public Map<String, Object> checkGenerates(@RequestParam String from, @RequestParam String to) {
        Map<String, Object> response = new HashMap<>();
        boolean result = fiveElementsService.isGenerates(from, to);
        response.put("code", 200);
        response.put("from", from);
        response.put("to", to);
        response.put("isGenerates", result);
        if (result) {
            response.put("message", from + " 生 " + to + "，相生关系成立");
        } else {
            response.put("message", from + " 不生 " + to);
        }
        return response;
    }
    
    /**
     * 判断相克关系
     */
    @GetMapping("/check/restricts")
    public Map<String, Object> checkRestricts(@RequestParam String from, @RequestParam String to) {
        Map<String, Object> response = new HashMap<>();
        boolean result = fiveElementsService.isRestricts(from, to);
        response.put("code", 200);
        response.put("from", from);
        response.put("to", to);
        response.put("isRestricts", result);
        if (result) {
            response.put("message", from + " 克 " + to + "，相克关系成立");
        } else {
            response.put("message", from + " 不克 " + to);
        }
        return response;
    }
}
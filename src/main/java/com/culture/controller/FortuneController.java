package com.culture.controller;

import com.culture.model.Fortune;
import com.culture.service.FortuneService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/fortune")
@CrossOrigin(origins = "*")
public class FortuneController {
    
    @Autowired
    private FortuneService fortuneService;
    
    /**
     * 获取今日运势
     */
    @GetMapping("/daily")
    public Map<String, Object> getDailyFortune(@RequestParam(required = false) String zodiac) {
        Map<String, Object> response = new HashMap<>();
        try {
            Fortune fortune = fortuneService.getDailyFortune(zodiac);
            response.put("code", 200);
            response.put("message", "success");
            response.put("data", fortune);
        } catch (Exception e) {
            response.put("code", 500);
            response.put("message", "获取运势失败: " + e.getMessage());
        }
        return response;
    }
    
    /**
     * 获取所有生肖
     */
    @GetMapping("/zodiacs")
    public Map<String, Object> getZodiacs() {
        Map<String, Object> response = new HashMap<>();
        List<String> zodiacs = fortuneService.getZodiacs();
        response.put("code", 200);
        response.put("data", zodiacs);
        return response;
    }
}
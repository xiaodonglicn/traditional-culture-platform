package com.culture.controller;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class CoordinateParser {

    // 最小保留的小数位数（不足补零，超出则原样保留）
    private static final int MIN_SCALE = 3;

    public static class Point3D {
        private final BigDecimal x;
        private final BigDecimal y;
        private final BigDecimal z;

        public Point3D(BigDecimal x, BigDecimal y, BigDecimal z) {
            this.x = x;
            this.y = y;
            this.z = z;
        }

        public BigDecimal getX() {
            return x;
        }

        public BigDecimal getY() {
            return y;
        }

        public BigDecimal getZ() {
            return z;
        }

        @Override
        public String toString() {
            return "Point3D{" +
                    "x=" + x.toPlainString() +
                    ", y=" + y.toPlainString() +
                    ", z=" + z.toPlainString() +
                    '}';
        }
    }

    /**
     * 动态调整小数位数：
     * - 如果当前小数位数 >= MIN_SCALE，保留原样（不做任何舍入）
     * - 如果当前小数位数 < MIN_SCALE，补零至 MIN_SCALE 位
     */
    private static BigDecimal adjustScale(BigDecimal value) {
        int currentScale = value.scale();
        if (currentScale < MIN_SCALE) {
            // 补零，不会改变数值大小，也不会四舍五入
            return value.setScale(MIN_SCALE, RoundingMode.UNNECESSARY);
        }
        // 超出 MIN_SCALE 位，原样返回，不丢失精度
        return value;
    }

    public static Point3D parseAndConvert(String input) {
        if (input == null || input.trim().isEmpty()) {
            throw new IllegalArgumentException("输入字符串不能为空");
        }

        Pattern pattern = Pattern.compile("(?i)([EWNSDU])\\s*([-+]?\\d+(?:\\.\\d+)?)\\s*([a-zA-Z]*)");
        Matcher matcher = pattern.matcher(input);

        BigDecimal x = null, y = null, z = null;

        while (matcher.find()) {
            String direction = matcher.group(1).toUpperCase();
            BigDecimal value = new BigDecimal(matcher.group(2));
            String unit = matcher.group(3).toLowerCase();

            // 单位换算：毫米转米
            if ("mm".equals(unit)) {
                value = value.divide(new BigDecimal("1000"));
            } else if ("cm".equals(unit)) {
                value = value.divide(new BigDecimal("100"));
            }

            // ⭐ 关键：动态调整小数位数（不足补零，超出保留）
            value = adjustScale(value);

            // 根据规则映射到 XYZ
            switch (direction) {
                case "E":
                    x = value;
                    break;
                case "W":
                    x = value.negate();
                    break;
                case "N":
                    y = value;
                    break;
                case "S":
                    y = value.negate();
                    break;
                case "U":
                    z = value;
                    break;
                case "D":
                    z = value.negate();
                    break;
                default:
                    break;
            }
        }

        if (x == null || y == null || z == null) {
            throw new IllegalArgumentException("输入的字符串缺少必要的坐标信息 (E/W, N/S, U/D)");
        }

        return new Point3D(x, y, z);
    }

    public static void main(String[] args) {
        String input = "E 54436.65mm N 15300mm D 8100mm";

        try {
            Point3D point = parseAndConvert(input);

            System.out.println("input：" + input);
            System.out.println("转换结果 (不足 " + MIN_SCALE + " 位补零，超出保留原样):");
            System.out.println(point);

            System.out.println("X = " + point.getX().toPlainString());
            System.out.println("Y = " + point.getY().toPlainString());
            System.out.println("Z = " + point.getZ().toPlainString());
            System.out.println("point= " + point);

        } catch (IllegalArgumentException e) {
            System.err.println("解析错误: " + e.getMessage());
        }
    }
}
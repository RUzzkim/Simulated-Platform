package com.platform.robotcloud.publish;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 参数（按设备）/ 策略（全局，可下发到任意设备）/ 模型（按设备 + 模型名）的版本化与下发。
 * 路径刻意分两处：设备相关挂在 /api/devices/{id}/** 下，策略本体是全局资源。
 */
@RestController
public class PublishController {

    private final PublishService service;

    public PublishController(PublishService service) {
        this.service = service;
    }

    // ------------------------------------------------------------ 设备参数

    @GetMapping("/api/devices/{id}/parameters")
    public List<ParameterView> parameters(@PathVariable Long id,
                                          @RequestParam(defaultValue = "50") int limit) {
        return service.parameters(id, limit);
    }

    @PostMapping("/api/devices/{id}/parameters")
    public ParameterView createParameter(@PathVariable Long id, @Valid @RequestBody ParameterRequest request) {
        return service.createParameter(id, request.payload());
    }

    @GetMapping("/api/devices/{id}/parameters/{version}")
    public ParameterView parameter(@PathVariable Long id, @PathVariable int version) {
        return service.parameter(id, version);
    }

    @PostMapping("/api/devices/{id}/parameters/{version}/publish")
    public PublishResult publishParameter(@PathVariable Long id, @PathVariable int version) {
        return service.publishParameter(id, version);
    }

    // ------------------------------------------------------------ 设备模型

    @GetMapping("/api/devices/{id}/models")
    public List<ModelView> models(@PathVariable Long id,
                                  @RequestParam(required = false) String modelName,
                                  @RequestParam(defaultValue = "50") int limit) {
        return service.models(id, modelName, limit);
    }

    @PostMapping("/api/devices/{id}/models")
    public ModelView createModel(@PathVariable Long id, @Valid @RequestBody ModelRequest request) {
        return service.createModel(id, request.modelName(), request.artifactUrl(), request.metadata());
    }

    @GetMapping("/api/devices/{id}/models/{modelName}/{version}")
    public ModelView model(@PathVariable Long id, @PathVariable String modelName, @PathVariable int version) {
        return service.model(id, modelName, version);
    }

    @PostMapping("/api/devices/{id}/models/{modelName}/{version}/publish")
    public PublishResult publishModel(@PathVariable Long id, @PathVariable String modelName,
                                      @PathVariable int version) {
        return service.publishModel(id, modelName, version);
    }

    // ---------------------------------------------------- 策略（全局）+ 下发

    @GetMapping("/api/strategies")
    public List<StrategyView> strategies(@RequestParam(required = false) String name,
                                         @RequestParam(defaultValue = "50") int limit) {
        return service.strategies(name, limit);
    }

    @PostMapping("/api/strategies")
    public StrategyView createStrategy(@Valid @RequestBody StrategyRequest request) {
        return service.createStrategy(request.name(), request.payload());
    }

    @GetMapping("/api/strategies/{name}/{version}")
    public StrategyView strategy(@PathVariable String name, @PathVariable int version) {
        return service.strategy(name, version);
    }

    @PostMapping("/api/devices/{id}/strategies/{name}/{version}/publish")
    public PublishResult publishStrategy(@PathVariable Long id, @PathVariable String name,
                                         @PathVariable int version) {
        return service.publishStrategy(id, name, version);
    }

    // ------------------------------------------------------- 当前生效配置

    @GetMapping("/api/devices/{id}/publishables")
    public PublishablesView publishables(@PathVariable Long id) {
        return service.publishables(id);
    }
}
package com.platform.robotcloud.command;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/devices/{id}/commands")
public class CommandController {

    private final CommandService commandService;

    public CommandController(CommandService commandService) {
        this.commandService = commandService;
    }

    @PostMapping
    public CommandLog dispatch(@PathVariable Long id, @Valid @RequestBody CommandRequest request) {
        return commandService.dispatch(id, request);
    }

    @GetMapping
    public List<CommandLog> list(
            @PathVariable Long id,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return commandService.history(id, page, size);
    }
}
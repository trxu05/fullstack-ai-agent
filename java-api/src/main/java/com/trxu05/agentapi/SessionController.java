package com.trxu05.agentapi;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
@CrossOrigin(origins = "*")
@Validated
public class SessionController {

    private final Map<String, Boolean> sessions = new ConcurrentHashMap<>();
    private final RestClient agentClient;

    public SessionController(@Value("${agent.base-url:http://127.0.0.1:8001}") String agentBaseUrl) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(5));
        factory.setReadTimeout(Duration.ofSeconds(120));
        this.agentClient = RestClient.builder().baseUrl(agentBaseUrl).requestFactory(factory).build();
    }

    @PostMapping("/sessions")
    public Map<String, String> createSession(@RequestBody(required = false) Map<String, String> body) {
        String requested = body == null ? null : body.get("sessionId");
        String id = (requested != null && !requested.isBlank()) ? requested.trim() : UUID.randomUUID().toString();
        sessions.put(id, Boolean.TRUE);
        try {
            agentClient.get().uri("/board?session_id={id}", id).retrieve().toBodilessEntity();
        } catch (Exception ignored) {
            // Agent may not be up yet; UI will retry via /board
        }
        return Map.of("sessionId", id);
    }

    @GetMapping("/sessions/{id}/board")
    public Map<?, ?> getBoard(@PathVariable String id) {
        requireSession(id);
        Map<?, ?> board = agentClient.get()
                .uri("/board?session_id={id}", id)
                .retrieve()
                .body(Map.class);
        if (board == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "empty board");
        }
        return board;
    }

    @PostMapping("/sessions/{id}/courses")
    public Map<?, ?> addCourse(@PathVariable String id, @RequestBody Map<String, Object> body) {
        requireSession(id);
        return postBoard("/board/courses?session_id=" + id, body);
    }

    @PostMapping("/sessions/{id}/tasks")
    public Map<?, ?> addTask(@PathVariable String id, @RequestBody Map<String, Object> body) {
        requireSession(id);
        return postBoard("/board/tasks?session_id=" + id, body);
    }

    @PostMapping("/sessions/{id}/tasks/{taskId}/done")
    public Map<?, ?> completeTask(@PathVariable String id, @PathVariable String taskId) {
        requireSession(id);
        Map<?, ?> resp = agentClient.post()
                .uri("/board/tasks/{taskId}/done?session_id={id}", taskId, id)
                .retrieve()
                .body(Map.class);
        if (resp == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "empty response");
        }
        return resp;
    }

    @PostMapping("/sessions/{id}/materials")
    public Map<?, ?> addMaterial(@PathVariable String id, @RequestBody Map<String, Object> body) {
        requireSession(id);
        return postBoard("/board/materials?session_id=" + id, body);
    }

    @PutMapping("/sessions/{id}/materials/{materialId}")
    public Map<?, ?> editMaterial(
            @PathVariable String id,
            @PathVariable String materialId,
            @RequestBody Map<String, Object> body) {
        requireSession(id);
        Map<?, ?> resp = agentClient.put()
                .uri("/board/materials/{materialId}?session_id={id}", materialId, id)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(Map.class);
        if (resp == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "empty response");
        }
        return resp;
    }

    @PostMapping("/sessions/{id}/chat")
    public ChatResponse chat(@PathVariable String id, @RequestBody @Validated ChatRequest request) {
        requireSession(id);

        AgentReply agentReply;
        try {
            Map<String, Object> payload = new HashMap<>();
            payload.put("message", request.message());
            payload.put("session_id", id);
            if (request.history() != null) {
                payload.put("history", request.history());
            }
            agentReply = agentClient.post()
                    .uri("/agent/chat")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(payload)
                    .retrieve()
                    .body(AgentReply.class);
        } catch (Exception ex) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_GATEWAY, "agent unavailable — is Python :8001 up? (" + ex.getMessage() + ")");
        }

        if (agentReply == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "empty agent response");
        }

        return new ChatResponse(agentReply.reply(), agentReply.tools_used(), agentReply.provider());
    }

    private Map<?, ?> postBoard(String uri, Map<String, Object> body) {
        Map<?, ?> resp = agentClient.post()
                .uri(uri)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(Map.class);
        if (resp == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "empty response");
        }
        return resp;
    }

    private void requireSession(String id) {
        // Resume after gateway restart: SQLite on the agent is the source of truth.
        sessions.putIfAbsent(id, Boolean.TRUE);
    }

    public record ChatTurn(String role, String text) {}

    public record ChatRequest(@NotBlank String message, List<ChatTurn> history) {}

    public record ChatResponse(
            String reply,
            @JsonProperty("toolsUsed") List<Map<String, Object>> toolsUsed,
            String provider) {}

    public record AgentReply(
            String reply,
            @JsonAlias("tools_used") @JsonProperty("tools_used") List<Map<String, Object>> tools_used,
            String provider) {}
}

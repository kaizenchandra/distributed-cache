package dev.cache;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class Errors {
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<?> invalid(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(java.util.Map.of("error", "INVALID_REQUEST"));
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<?> unavailable(IllegalStateException e) {
        org.slf4j.LoggerFactory.getLogger(Errors.class).warn("cache operation unavailable", e);
        return ResponseEntity.status(503).body(java.util.Map.of("error", "UNAVAILABLE_OR_AMBIGUOUS", "message", e.getMessage()));
    }
}

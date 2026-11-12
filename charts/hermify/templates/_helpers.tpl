{{/* Labels on every object. Selectors use only app/tenant, which never change. */}}
{{- define "hermify.labels" -}}
app.kubernetes.io/part-of: hermify
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{/* Labels on pod templates: no chart version, so a chart release alone doesn't restart pods. */}}
{{- define "hermify.podLabels" -}}
app.kubernetes.io/part-of: hermify
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* storageClassName line for a PVC spec, or nothing for the cluster default. */}}
{{- define "hermify.storageClass" -}}
{{- if .Values.storageClassName }}
storageClassName: {{ .Values.storageClassName }}
{{- end }}
{{- end }}

{{- define "hermify.hindsightUrl" -}}
http://hindsight.{{ .Release.Namespace }}.svc.cluster.local:8888
{{- end }}

{{/* Per-tenant values. Call with (dict "root" $ "t" $tenant). */}}
{{- define "hermify.secretName" -}}
{{- .t.existingSecret | default (printf "hermes-%s-secrets" .t.name) }}
{{- end }}

{{- define "hermify.modelName" -}}
{{- .t.modelName | default (printf "hermes-%s" .t.name) }}
{{- end }}

{{- define "hermify.bankId" -}}
{{- .t.bankId | default (printf "hermes-%s" .t.name) }}
{{- end }}

{{/* Checks that fail the render early, with a readable message. */}}
{{- define "hermify.validate" -}}
{{- $seen := dict }}
{{- range $t := .Values.tenants }}
{{- if not (regexMatch "^[a-z][a-z0-9-]{0,30}[a-z0-9]$|^[a-z]$" (toString $t.name)) }}
{{- fail (printf "tenants: %q is not a valid name (lowercase letters, digits and -, starting with a letter, at most 32)" (toString $t.name)) }}
{{- end }}
{{- if hasKey $seen $t.name }}
{{- fail (printf "tenants: %q is listed twice" $t.name) }}
{{- end }}
{{- $_ := set $seen $t.name true }}
{{- $box := $t.box | default dict }}
{{- if and $box.enabled (not $box.authorizedKeys) }}
{{- fail (printf "tenants[%s].box: enabled without authorizedKeys (nobody could log in)" $t.name) }}
{{- end }}
{{- end }}
{{- if and .Values.tenants (or (not .Values.llm.baseUrl) (not .Values.llm.model)) }}
{{- fail "llm.baseUrl and llm.model are required" }}
{{- end }}
{{- if not (regexMatch "^[A-Za-z_][A-Za-z0-9_]*$" .Values.llm.apiKeyEnv) }}
{{- fail "llm.apiKeyEnv must be a valid env var name" }}
{{- end }}
{{- end }}

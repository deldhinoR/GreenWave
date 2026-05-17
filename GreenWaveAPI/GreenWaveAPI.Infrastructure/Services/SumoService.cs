using GreenWaveAPI.Application.DTOs;
using GreenWaveAPI.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using System.Net.Http.Json;

public class SumoService : ISumoService
{
    private readonly HttpClient _httpClient;
    private readonly string _sumoBaseUrl;
    private readonly bool _enabled;

    public SumoService(HttpClient httpClient, IConfiguration configuration)
    {
        _httpClient = httpClient;
        _sumoBaseUrl = configuration["Sumo:BaseUrl"] ?? "http://localhost:5001";
        _enabled = bool.TryParse(configuration["Sumo:Enabled"], out var enabled) && enabled;
    }

    public async Task SendToSumoAsync(SumoTrafficDto data)
    {
        if (!_enabled)
        {
            return;
        }

        var baseUrl = _sumoBaseUrl.TrimEnd('/');
        var response = await _httpClient.PostAsJsonAsync(
            $"{baseUrl}/sumo/update",   // Python bridge endpoint
            data);

        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync();
            throw new Exception($"SUMO error: {error}");
        }
    }
}


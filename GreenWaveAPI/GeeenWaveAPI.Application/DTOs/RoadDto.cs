using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace GreenWaveAPI.Application.DTOs;

public class RoadDto
{
    [JsonPropertyName("road_id")]
    public int RoadId { get; set; }

    [JsonPropertyName("congestion_score")]
    public int CongestionScore { get; set; }

    [JsonPropertyName("ambulance")]
    public bool Ambulance { get; set; }
}

